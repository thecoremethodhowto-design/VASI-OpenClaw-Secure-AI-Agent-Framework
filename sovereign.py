"""Sovereign: sapma denetcisi.

NE YAPAR: Sistemin guvenlik durusunun bir anlik goruntusunu alir ve
kodun, politikanin ve yapilandirmanin hala birbiriyle uyumlu oldugunu
dogrular. Bir sapma bulursa raporlar.

NEDEN VAR: Testler kodu dogrular -- ama siz calistirdiginizda. Sovereign
calisan sistemi dogrular, ayaktayken. Bu ayrim onemli: guvenlik aciklari
genelde eksik araclardan degil, erken yazilip sonra hic guncellenmeyen
yapilandirmalardan cikar.

Bu projede tam olarak bu uc kez yasandi:
  - Siniflandirma sirasi aylarca yanlisti (politika yazildi, kod degisti,
    kimse karsilastirmadi)
  - init_schema() yazildi, hicbir yerden cagrilmadi
  - Dokuz komut model gateway'ini atliyordu

Ucu de ayni sinif: sistem, yaptigini soyledigi seyi yapmiyordu.

KATMAN NOTU: Sovereign HICBIR yerel modulu import etmez. Denetledigi
sabitler ona ANLIK GORUNTU olarak verilir. Boylece denetledigi bir
moduldeki sorun denetciyi de bozamaz -- ve denetci, denetledigi seyin
calisma zamanina bagli olmadan test edilebilir.

KONTROL TURLERI -- bu ayrim her seyi belirler:

  DETERMINISTIK bir kontrol bir OLGU soyler:
      "Arac listesinde politikada olmayan bir isim var."
    Dogru ya da yanlis. Tartisma yok. Durdurabilir.

  SEZGISEL bir kontrol bir TAHMIN soyler:
      "Bu kullanim oruntusu olagandisi gorunuyor."
    Hakli olabilir, olmayabilir. YALNIZCA raporlar.

Sezgisel bir kontrol durdurursa, yanlis alarm operatoru kendi
sisteminden kilitler. Ve bir-iki yanlis alarmdan sonra insanlar
kontrolu kapatir. Kapali bir kontrol, olmayan bir kontroldur.
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("vasi")

# ── TURLER ────────────────────────────────────────────────────────────────────

DETERMINISTIK = "deterministik"
SEZGISEL = "sezgisel"

# ── YETENEKLER ────────────────────────────────────────────────────────────────

# Bir sapma tespit edildiginde HANGI yetenegin kapanacagi.
#
# Tek bir sapma yuzunden butun sistemi durdurmak guvenlik onlemi degil,
# hizmet kesintisidir. Ve operasyon ekibi ilk firsatta o onlemi kaldirir.
# Sapma hangi yetenegi etkiliyorsa yalnizca o kapanir.
YETENEK_RAG = "rag"                    # /indeksle, /bul, /sor
YETENEK_ARACLAR = "araclar"            # model arac cagirma
YETENEK_HAFIZA = "hafiza_prompt"       # hatiralarin sistem promptuna girmesi
YETENEK_YOK = "yok"                    # yalnizca bilgi; hicbir sey kapanmaz

GECERLI_YETENEKLER = (
    YETENEK_RAG, YETENEK_ARACLAR, YETENEK_HAFIZA, YETENEK_YOK,
)

# ── ONEM DERECELERI ───────────────────────────────────────────────────────────

# Ayirici olcut GERI ALINABILIRLIK: sapma tespit edildi, bir sonraki
# saniye ne olabilir?
#
#   KRITIK  -> geri alinamaz bir sey olabilir (sizan bir anahtar geri gelmez)
#   UYARI   -> bir sey ters ama zarari geri alinabilir
#   BILGI   -> kayda deger ama zararsiz
KRITIK = "kritik"
UYARI = "uyari"
BILGI = "bilgi"


@dataclass(frozen=True)
class Bulgu:
    """Bir kontrolun tespit ettigi sapma."""
    kontrol: str
    tur: str
    onem: str
    yetenek: str
    mesaj: str

    @property
    def durdurabilir(self) -> bool:
        """Bu bulgu bir yetenegi kapatabilir mi?

        UC KOSUL, ucu de gerekli:
          1. Deterministik olmali -- tahmin bir yetenegi kapatamaz
          2. Kritik olmali -- geri alinabilir bir sorun icin durdurmaya degmez
          3. Kapatilacak bir yetenek gostermeli
        """
        return (
            self.tur == DETERMINISTIK
            and self.onem == KRITIK
            and self.yetenek != YETENEK_YOK
        )


@dataclass
class DenetimSonucu:
    """Bir denetim turunun tum ciktisi."""
    bulgular: list[Bulgu] = field(default_factory=list)
    calisan_kontrol: int = 0
    hatali_kontrol: list[str] = field(default_factory=list)

    @property
    def temiz(self) -> bool:
        return not self.bulgular

    @property
    def kapanacak_yetenekler(self) -> set[str]:
        """Faz 2'de kullanilacak: hangi yetenekler kapatilmali?"""
        return {b.yetenek for b in self.bulgular if b.durdurabilir}


# ── KONTROLLER ────────────────────────────────────────────────────────────────
#
# Her kontrol bir anlik goruntu sozlugu alir ve Bulgu listesi dondurur.
# Bos liste = sapma yok.
#
# Kontroller anlik goruntude bir alan EKSIKSE sessizce gecer (bos liste
# dondurur). Eksik alani yakalamak denetcinin isi degil; anlik goruntuyu
# toplayan tarafin. Boylece bir alan eklenirken denetci cokmez.


def kontrol_politika_kod_uyumu(g: dict) -> list[Bulgu]:
    """Politika dosyasindaki her sinif kodda taninıyor mu?

    Bu kontrol dogrudan yasanmis bir hatadan dogdu: politikaya bir sinif
    eklenip SINIF_ONCELIGI guncellenmezse, yeni sinif oncelik listesinin
    sonuna duser ve gevsek siniflarin arkasinda kalir.
    """
    oncelik = g.get("sinif_onceligi")
    politika = g.get("politika_siniflari")
    if oncelik is None or politika is None:
        return []

    eksik = sorted(set(politika) - set(oncelik))
    if not eksik:
        return []
    return [Bulgu(
        kontrol="politika_kod_uyumu",
        tur=DETERMINISTIK,
        onem=KRITIK,
        yetenek=YETENEK_RAG,
        mesaj=(
            f"Politikada tanimli ama kodun oncelik listesinde olmayan sinif: "
            f"{', '.join(eksik)}. Bu siniflar en gevsek muameleyi gorur."
        ),
    )]


# Politikadaki boolean izin alanlari. Hepsi ayni mantiga tabi.
IZIN_ALANLARI = ("rag_allowed", "gemini_allowed", "external_share_allowed")


def kontrol_politika_izin_mantigi(g: dict) -> list[Bulgu]:
    """Daha kisitlayici bir sinif, daha gevsekten FAZLA izne sahip olamaz.

    kontrol_politika_kod_uyumu YAPIYA bakar: politikadaki sinif kodun
    listesinde var mi? Bu kontrol ANLAMA bakar: izinler siniflarin
    kisitlilik sirasiyla tutarli mi?

    Ikisi ayri sorunlar. Bir sinif listede olabilir ve yine de yanlis
    izne sahip olabilir -- SECRET'in rag_allowed degeri true yapilirsa
    yapisal hicbir sey bozulmaz, ama en gizli dosyalar indekslenir.

    Kural: SINIF_ONCELIGI en kisitlidan en gevsege gider. Bir izin bu
    sirada bir kez aciliyorsa, daha gevsek siniflarda kapanamaz.
    """
    oncelik = g.get("sinif_onceligi")
    politika = g.get("politika_siniflari")
    if not oncelik or not politika:
        return []

    bulgular = []
    for alan in IZIN_ALANLARI:
        sirali = [
            (s, politika[s].get(alan, False) is True)
            for s in oncelik if isinstance(politika.get(s), dict)
        ]
        for i, (kisitli, izinli) in enumerate(sirali):
            if not izinli:
                continue
            gevsek_ama_kapali = [s for s, d in sirali[i + 1:] if not d]
            if not gevsek_ama_kapali:
                continue
            bulgular.append(Bulgu(
                kontrol="politika_izin_mantigi",
                tur=DETERMINISTIK,
                onem=KRITIK,
                # Yalnizca elimizde kolu olan yetenegi kapatiyoruz.
                yetenek=YETENEK_RAG if alan == "rag_allowed" else YETENEK_YOK,
                mesaj=(
                    f"{alan}: {kisitli} sinifi izinli, ama daha gevsek olan "
                    f"{', '.join(gevsek_ama_kapali)} degil. Daha kisitlayici "
                    f"bir sinif daha fazla izne sahip olamaz."
                ),
            ))
            break  # Bu alan icin ilk ihlal yeter
    return bulgular


def kontrol_sinif_alanlari(g: dict) -> list[Bulgu]:
    """Bir sinif tanimi yalnizca bilinen alanlari icermeli.

    NEDEN: YAML'da girinti kayarsa bir blok komsu sinifin ICINE duser.
    Ayni sozlukte tekrar eden anahtar sessizce ustekini ezer -- PyYAML
    uyarmaz. Sonuc: yeni sinif hic olusmaz, eski sinifin izni degisir.

    Bu tam olarak yasandi. INTERNAL adli bir sinif eklenmek istendi;
    blok bir seviye iceri kaydi, SECRET'in rag_allowed degeri true
    oldu ve SECRET'in icinde bos bir INTERNAL anahtari kaldi.

    politika_izin_mantigi bu durumda TEHLIKEYI bildirir. Bu kontrol
    YERI bildirir: hangi sinifin icinde ne var. Ikisi ayri is --
    "bir sey yanlis" ile "su satir yanlis" ayni cumle degildir.
    """
    politika = g.get("politika_siniflari")
    if not politika:
        return []

    bilinen = set(IZIN_ALANLARI) | {"description"}
    bulgular = []
    for sinif, alanlar in sorted(politika.items()):
        if not isinstance(alanlar, dict):
            continue
        beklenmeyen = sorted(set(alanlar) - bilinen)
        if not beklenmeyen:
            continue
        bulgular.append(Bulgu(
            kontrol="sinif_alanlari",
            tur=DETERMINISTIK,
            onem=UYARI,
            yetenek=YETENEK_YOK,
            mesaj=(
                f"{sinif} sinifinin icinde beklenmeyen anahtar: "
                f"{', '.join(beklenmeyen)}. Girinti kaymis olabilir -- "
                f"bu anahtar ayri bir sinif olarak tanimlanmak istenmis olabilir."
            ),
        ))
    return bulgular


def kontrol_rag_izni_tanimli(g: dict) -> list[Bulgu]:
    """Her sinifin rag_allowed alani acikca tanimli mi?

    Tanimsiz alan varsayilan olarak False sayilir -- yani guvenli.
    Ama sessiz bir varsayilan, bilincli bir karardan farklidir.
    """
    politika = g.get("politika_siniflari")
    if not politika:
        return []

    eksik = sorted(s for s, alanlar in politika.items() if "rag_allowed" not in alanlar)
    if not eksik:
        return []
    return [Bulgu(
        kontrol="rag_izni_tanimli",
        tur=DETERMINISTIK,
        onem=UYARI,
        yetenek=YETENEK_YOK,
        mesaj=(
            f"Su siniflarda rag_allowed tanimli degil: {', '.join(eksik)}. "
            "Varsayilan olarak indekslenmezler, ama karar acik yazilmali."
        ),
    )]


def kontrol_arac_listesi(g: dict) -> list[Bulgu]:
    """Modele sunulan araclar izin listesiyle birebir esliyor mu?

    Iki yonlu kontrol:
      - Sunulan ama izinli olmayan bir arac: model cagirir, reddedilir
      - Izinli ama sunulmayan bir arac: olu izin, saldiri yuzeyi
    """
    izinli = g.get("izinli_araclar")
    sunulan = g.get("sunulan_araclar")
    if izinli is None or sunulan is None:
        return []

    bulgular = []
    fazla = sorted(set(sunulan) - set(izinli))
    if fazla:
        bulgular.append(Bulgu(
            kontrol="arac_listesi",
            tur=DETERMINISTIK,
            onem=KRITIK,
            yetenek=YETENEK_ARACLAR,
            mesaj=(
                f"Modele sunulan ama izin listesinde olmayan arac: "
                f"{', '.join(fazla)}."
            ),
        ))

    olu = sorted(set(izinli) - set(sunulan))
    if olu:
        bulgular.append(Bulgu(
            kontrol="arac_listesi",
            tur=DETERMINISTIK,
            onem=UYARI,
            yetenek=YETENEK_YOK,
            mesaj=(
                f"Izin listesinde olup modele sunulmayan arac: "
                f"{', '.join(olu)}. Kullanilmayan izin, olu izindir."
            ),
        ))
    return bulgular


def kontrol_hafiza_kaynak_filtresi(g: dict) -> list[Bulgu]:
    """Sistem promptuna yalnizca guvenilir kaynakli hatiralar giriyor mu?

    MITRE'nin OpenClaw bulgusu: bellek kaynagina gore ayrismiyordu.
    Web'den kazinan veri ile kullanici komutu ayni guven seviyesindeydi.
    """
    girebilen = g.get("prompta_girebilen")
    gecerli = g.get("gecerli_kaynaklar")
    if girebilen is None:
        return []

    bulgular = []
    guvenilmeyen = sorted(set(girebilen) - {"user"})
    if guvenilmeyen:
        bulgular.append(Bulgu(
            kontrol="hafiza_kaynak_filtresi",
            tur=DETERMINISTIK,
            onem=KRITIK,
            yetenek=YETENEK_HAFIZA,
            mesaj=(
                f"Sistem promptuna kullanici disi kaynak girebiliyor: "
                f"{', '.join(guvenilmeyen)}."
            ),
        ))

    if gecerli is not None:
        tanimsiz = sorted(set(girebilen) - set(gecerli))
        if tanimsiz:
            bulgular.append(Bulgu(
                kontrol="hafiza_kaynak_filtresi",
                tur=DETERMINISTIK,
                onem=UYARI,
                yetenek=YETENEK_YOK,
                mesaj=(
                    f"Prompta girebilen ama semada tanimsiz kaynak: "
                    f"{', '.join(tanimsiz)}."
                ),
            ))
    return bulgular


def kontrol_onay_kapilari(g: dict) -> list[Bulgu]:
    """Kalici etkisi olan her komut onay istiyor mu?

    Yeni bir komut eklenip onay kapisi unutulursa, bu kontrol yakalar.
    """
    gereken = g.get("onay_gereken_komutlar")
    olan = g.get("onay_isteyen_komutlar")
    if gereken is None or olan is None:
        return []

    bulgular = []

    # Asil kontrol: kalici etkisi olup onay istemeyen komut.
    eksik = sorted(set(gereken) - set(olan))
    if eksik:
        bulgular.append(Bulgu(
            kontrol="onay_kapilari",
            tur=DETERMINISTIK,
            onem=KRITIK,
            yetenek=YETENEK_YOK,  # Faz 2'de komut bazli kapatmaya donusecek
            mesaj=(
                f"Kalici etkisi olup onay istemeyen komut: "
                f"{', '.join('/' + k for k in eksik)}."
            ),
        ))

    # TERS KONTROL: onay isteyip listede olmayan komut.
    #
    # Bu bir guvenlik acigi DEGIL -- fazla koruma zararsizdir. Ama
    # listenin geride kaldigini soyler. Denetcinin kendi tanimini
    # denetlemesi: bir liste ne kadar eskirse, asil kontrol o kadar
    # anlamsizlasir.
    fazla = sorted(set(olan) - set(gereken))
    if fazla:
        bulgular.append(Bulgu(
            kontrol="onay_kapilari",
            tur=DETERMINISTIK,
            onem=BILGI,
            yetenek=YETENEK_YOK,
            mesaj=(
                f"Onay isteyip listede olmayan komut: "
                f"{', '.join('/' + k for k in fazla)}. "
                "Guvenlik sorunu degil, ama liste guncellenmeli."
            ),
        ))
    return bulgular


def kontrol_rag_arac_yalitimi(g: dict) -> list[Bulgu]:
    """/sor kod yolunda arac yurutme var mi?

    Getirilen bir belgedeki enjeksiyon, model bir arac cagrisi uretse
    bile hicbir seyi calistiramamali -- cunku o kod yolunda arac
    yurutme YOKTUR. Birisi "madem tespit ettik, calistiralim" derse
    bu kontrol yakalar.
    """
    kaynak = g.get("aracsiz_fonksiyon_kaynagi")
    if not kaynak:
        return []

    yasakli = ("skill_web_radar(", "skill_get_time(", "_tool_result_message(")
    bulunan = sorted(y for y in yasakli if y in kaynak)
    if not bulunan:
        return []
    return [Bulgu(
        kontrol="rag_arac_yalitimi",
        tur=DETERMINISTIK,
        onem=KRITIK,
        yetenek=YETENEK_RAG,
        mesaj=(
            f"Aracsiz kod yolunda arac yurutme bulundu: {', '.join(bulunan)}. "
            "Belge enjeksiyonu artik dis dunyaya ulasabilir."
        ),
    )]


# ── PARMAK IZI ────────────────────────────────────────────────────────────────
#
# Yukaridaki kontroller KURALLARI dogrular: "su boyle olmali."
# Ama her sey icin kural yazilamaz. Geriye kalan sey su: bir alan dun
# neyse bugun de o mu?
#
# IZLENEN ALANLAR ACIK BIR LISTE -- "sunlar haric hepsi" degil. Ayni
# gerekce izin listelerindeki gibi: yasak listesi, eklenmesi unutulan
# seyi kapsamaz. Ayrica sayaclar (komut_sayisi, hata_sayisi) her
# komutta degisir; kapsama girselerdi her denetim "sapma var" derdi ve
# kontrol bir haftada kapatilirdi.

IZLENEN_ALANLAR = (
    "izinli_araclar",
    "sunulan_araclar",
    "sinif_onceligi",
    "politika_siniflari",
    "prompta_girebilen",
    "gecerli_kaynaklar",
    "onay_gereken_komutlar",
    "onay_isteyen_komutlar",
    "aracsiz_fonksiyon_kaynagi",
)

# Bu uzunlugu asan alan ozetlenir. Kisa alanlar oldugu gibi saklanir ki
# raporda "ne degisti" gorulebilsin; uzun olanlarda yalnizca "degisti"
# bilgisi kalir.
OZET_ESIGI = 200


def _kanonik(deger) -> str:
    """Degeri sirali, kararli bir metne cevirir.

    Kume ve liste siralanir: elemanlarin sirasi degistiginde parmak
    izi degismemeli, yoksa her yeniden baslatma sapma gorunur.
    """
    if isinstance(deger, dict):
        return json.dumps(
            {k: _kanonik(v) for k, v in sorted(deger.items())},
            ensure_ascii=False, sort_keys=True,
        )
    if isinstance(deger, (set, frozenset)):
        return json.dumps(sorted(str(x) for x in deger), ensure_ascii=False)
    if isinstance(deger, (list, tuple)):
        return json.dumps([_kanonik(x) for x in deger], ensure_ascii=False)
    return str(deger)


def parmak_izi(goruntu: dict) -> dict[str, str]:
    """Anlik goruntuyu alan-alan ozete cevirir.

    Saf fonksiyon: veritabani yok, saat yok, yan etki yok.
    """
    izi = {}
    for alan in IZLENEN_ALANLAR:
        if alan not in goruntu:
            continue
        metin = _kanonik(goruntu[alan])
        if len(metin) > OZET_ESIGI:
            metin = "sha256:" + hashlib.sha256(metin.encode("utf-8")).hexdigest()[:16]
        izi[alan] = metin
    return izi


def kontrol_zaman_sapmasi(g: dict) -> list[Bulgu]:
    """Gecen denetimden bu yana ne degisti?

    DEGISIKLIK, SAPMA DEGILDIR. Bir arac bilerek eklendiyse parmak izi
    degisir ve bu dogrudur. Bu yuzden onem her zaman BILGI ve hicbir
    yetenek kapanmaz.

    Tur yine de DETERMINISTIK: "su alan degisti" bir olgudur, tahmin
    degil. Tur ile onem ayri eksenler oldugu icin bu ikisi ayni anda
    soylenebiliyor -- olgu kesin, ama onemi dusuk.

    Kural yazilabilen her sey yukaridaki kontrollerde. Burasi geriye
    kalan: kural yazamadigimiz ama degistiginde haberdar olmak
    istedigimiz seyler. Politika dosyasi disaridan baglanip canli
    degistirilirse bu kontrol yakalar.
    """
    onceki = g.get("onceki_parmak_izi")
    if not onceki:
        return []  # Ilk denetim: karsilastiracak sey yok

    simdiki = parmak_izi(g)
    degisen = sorted(
        a for a in set(onceki) | set(simdiki)
        if onceki.get(a) != simdiki.get(a)
    )
    if not degisen:
        return []

    zaman = g.get("onceki_parmak_izi_zamani")
    ne_zaman = f" (son denetim: {zaman})" if zaman else ""
    return [Bulgu(
        kontrol="zaman_sapmasi",
        tur=DETERMINISTIK,
        onem=BILGI,
        yetenek=YETENEK_YOK,
        mesaj=(
            f"Gecen denetimden bu yana degisen alan: {', '.join(degisen)}"
            f"{ne_zaman}. Degisiklik kendiliginden sorun degildir; "
            f"bilerek yapildiysa yok sayin."
        ),
    )]


def kontrol_hata_orani(g: dict) -> list[Bulgu]:
    """SEZGISEL: komut hata orani olagandisi yuksek mi?

    Bu bir TAHMINDIR, olgu degil. Yuksek hata orani bir sorunun
    belirtisi OLABILIR -- ya da yeni bir ozellik deneniyordur, ya da
    Ollama kapalidir.

    Bu yuzden onemi asla KRITIK degildir ve hicbir yetenegi kapatmaz.
    Sezgisel bir kontrol durdurursa, yanlis alarm sizi kendi
    sisteminizden kilitler.
    """
    toplam = g.get("komut_sayisi")
    hata = g.get("hata_sayisi")
    esik = g.get("hata_orani_esigi", 0.5)
    if not toplam or hata is None or toplam < 10:
        return []  # Az ornekte oran anlamsiz

    oran = hata / toplam
    if oran < esik:
        return []
    return [Bulgu(
        kontrol="hata_orani",
        tur=SEZGISEL,
        onem=UYARI,
        yetenek=YETENEK_YOK,
        mesaj=(
            f"Komutlarin %{oran * 100:.0f}'i hatayla sonuclandi "
            f"({hata}/{toplam}). Bu bir tahmindir; sebebi arastirilmali."
        ),
    )]


# Kontrol sirasi = rapor sirasi. En kritikten baslar.
KONTROLLER = (
    kontrol_politika_kod_uyumu,
    kontrol_politika_izin_mantigi,
    kontrol_sinif_alanlari,
    kontrol_arac_listesi,
    kontrol_hafiza_kaynak_filtresi,
    kontrol_rag_arac_yalitimi,
    kontrol_onay_kapilari,
    kontrol_rag_izni_tanimli,
    kontrol_zaman_sapmasi,
    kontrol_hata_orani,
)


# ── DENETIM ───────────────────────────────────────────────────────────────────

def audit(goruntu: dict) -> DenetimSonucu:
    """Tum kontrolleri calistirir ve sonucu dondurur.

    Bir kontrol beklenmedik bir hata verirse DIGERLERI CALISMAYA DEVAM
    EDER. Denetcinin kendisi, korudugu seyden daha buyuk bir risk
    olmamali. Ama sessizce de gecmez: hatali kontrol sonuca yazilir.
    """
    sonuc = DenetimSonucu()
    for kontrol in KONTROLLER:
        try:
            sonuc.bulgular.extend(kontrol(goruntu))
            sonuc.calisan_kontrol += 1
        except Exception as e:
            sonuc.hatali_kontrol.append(kontrol.__name__)
            logger.warning(f"⚠️ Denetim kontrolu hata verdi: {kontrol.__name__}: {e}")
    return sonuc


def format_report(sonuc: DenetimSonucu) -> str:
    """Denetim sonucunu okunur metne cevirir."""
    if sonuc.temiz and not sonuc.hatali_kontrol:
        return (
            f"🛡️ Denetim temiz\n\n"
            f"{sonuc.calisan_kontrol} kontrol çalıştı, sapma bulunamadı.\n\n"
            "_Kod, politika ve yapılandırma birbiriyle uyumlu._"
        )

    satirlar = ["🛡️ Denetim sonucu\n"]
    simgeler = {KRITIK: "🔴", UYARI: "🟡", BILGI: "🔵"}

    for b in sonuc.bulgular:
        simge = simgeler.get(b.onem, "•")
        satirlar.append(f"{simge} {b.kontrol} ({b.tur})")
        satirlar.append(f"   {b.mesaj}")
        if b.durdurabilir:
            satirlar.append(f"   ↳ Etkilenen yetenek: {b.yetenek}")
        satirlar.append("")

    if sonuc.hatali_kontrol:
        satirlar.append(
            f"⚠️ Çalıştırılamayan kontrol: {', '.join(sonuc.hatali_kontrol)}"
        )
        satirlar.append("")

    satirlar.append(f"{sonuc.calisan_kontrol} kontrol çalıştı.")
    return "\n".join(satirlar)


# ── YETENEK KAPISI ────────────────────────────────────────────────────────────
#
# Faz 1 yalnizca rapor ediyordu. Burasi raporu EYLEME cevirir.
#
# Tasarim karari -- neden bir guvenlik kontrolune "kapat" dugmesi var?
#
# Cunku dugme olmazsa operator kontrolu tamamen soker. Bu dosyanin ust
# kismindaki gerekcenin aynisi: kapali bir kontrol, olmayan bir kontroldur.
# Gecersiz kilma yolu OLMAYAN bir kapatma, ilk acil durumda kodu
# degistirerek asilir -- ve bir daha geri konmaz.
#
# Ama dugmenin bedeli var, o yuzden dort sarti birden tasir:
#   1. ACIK olmali      -- kod degistirerek degil, komutla
#   2. ONAYLI olmali    -- tek tusla kazayla acilmamali
#   3. IZ birakmali     -- kim, neyi, ne zaman
#   4. SURELI olmali    -- suresiz gecersiz kilma, kontrolu silmektir
#
# Dorduncusu en onemlisi. Bu sistem bu ilkeye zaten inaniyor:
# PENDING_ACTION_TTL_SECONDS, bekleyen bir onayin suresiz acik
# kalmamasi icin var. Ayni ilke, kontrolun kapatma dugmesi icin de
# gecerli: sure dolunca yetenek kendiliginden yeniden kapanir ve
# operator asil sorunu cozmek zorunda kalir.


@dataclass
class YetenekKapisi:
    """Hangi yeteneklerin acik oldugunu tutar.

    Denetim sonucu buraya UYGULANIR; komutlar buraya SORAR.
    """
    kapali: dict[str, str] = field(default_factory=dict)
    gecersiz_kilmalar: dict[str, datetime] = field(default_factory=dict)

    def uygula(self, sonuc: DenetimSonucu) -> set[str]:
        """Denetim sonucunu uygular ve YENI kapanan yetenekleri dondurur.

        Onceki kapatmalar SIFIRLANIR: temiz bir denetim her seyi yeniden
        acar. Denetim tek yetkilidir -- eski bir bulgu, duzeltildikten
        sonra yetenegi kapali tutmaya devam edemez.

        Gecersiz kilmalar sifirlanmaz: onlar operatorun karari, denetimin
        degil. Zaten kendi sureleri dolunca kalkarlar.
        """
        onceki = set(self.kapali)
        self.kapali = {
            b.yetenek: f"{b.kontrol}: {b.mesaj}"
            for b in sonuc.bulgular if b.durdurabilir
        }
        return set(self.kapali) - onceki

    def _gecersiz_kilma_aktif(self, yetenek: str, simdi: datetime | None = None) -> bool:
        bitis = self.gecersiz_kilmalar.get(yetenek)
        if bitis is None:
            return False
        if (simdi or datetime.now(timezone.utc)) >= bitis:
            # Suresi doldu: kaydi temizle ki durum raporu yanlis soylemesin.
            self.gecersiz_kilmalar.pop(yetenek, None)
            return False
        return True

    def acik(self, yetenek: str, simdi: datetime | None = None) -> bool:
        """Bu yetenek su an kullanilabilir mi?"""
        if yetenek not in self.kapali:
            return True
        return self._gecersiz_kilma_aktif(yetenek, simdi)

    def neden_kapali(self, yetenek: str) -> str | None:
        """Kapali degilse None. Kapaliysa hangi bulgunun kapattigi."""
        return self.kapali.get(yetenek)

    def gecersiz_kil(self, yetenek: str, saniye: int,
                     simdi: datetime | None = None) -> datetime:
        """Bir yetenegi GECICI olarak yeniden acar. Bitis zamanini dondurur."""
        bitis = (simdi or datetime.now(timezone.utc)) + timedelta(seconds=saniye)
        self.gecersiz_kilmalar[yetenek] = bitis
        logger.warning(
            f"🔓 Yetenek gecersiz kilindi: {yetenek} -- bitis {bitis.isoformat()}"
        )
        return bitis

    def geri_al(self, yetenek: str) -> bool:
        """Gecersiz kilmayi suresi dolmadan kaldirir."""
        return self.gecersiz_kilmalar.pop(yetenek, None) is not None

    def durum_satiri(self, simdi: datetime | None = None) -> str:
        """/saglik icin tek satirlik ozet."""
        if not self.kapali:
            return "Tüm yetenekler açık."
        simdi = simdi or datetime.now(timezone.utc)
        parcalar = []
        for yetenek in sorted(self.kapali):
            if self._gecersiz_kilma_aktif(yetenek, simdi):
                kalan = int((self.gecersiz_kilmalar[yetenek] - simdi).total_seconds() // 60)
                parcalar.append(f"{yetenek} (geçersiz kılındı, ~{kalan} dk)")
            else:
                parcalar.append(f"{yetenek} (kapalı)")
        return "Sapma nedeniyle etkilenen: " + ", ".join(parcalar)