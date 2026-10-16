"""Denetim izi zinciri: her satir bir oncekinin ozetini tasir.

KATMAN KURALI: Bu modul hicbir yerel modulu import etmez; yalnizca
standart kutuphaneyi kullanir. Iki sebep:

  1) Dogrulayici, denetledigi sistemden BAGIMSIZ olmali. Zinciri
     kontrol eden kod, zinciri yazan sistemin geri kalanina
     guvenmemeli.
  2) Konteyner olmadan, kendi bilgisayarinizda calisabilmeli:

         python3 audit_chain.py denetim/denetim.log

     macOS'un sistem Python'i 3.9; bu dosya 3.9 ile uyumlu tutulur
     (from __future__ import annotations bu yuzden var).

SATIR BICIMI

    <zaman> - vasi - INFO - AUDIT | olay | user=***422 | ayrinti | sira=17 | ozet=<32 hex>

    govde = satirin " | ozet=" oncesindeki her sey (sira dahil)
    ozet  = SHA-256(onceki_ozet + "\\n" + govde) -- ilk 32 hex, 128 bit

    Ilk halkanin oncekisi BASLANGIC ("0" x 32). sira 1'den baslar ve
    bosluksuz artar; yeniden baslatmada kaldigi yerden devam eder.

NE YAKALAR
    - degistirilen satir      (ozet tutmuyor)
    - silinen satir           (sira atliyor)
    - araya eklenen satir     (sira tekrarliyor ya da zincirsiz satir)
    - yarim kalan satir       (yazma sirasinda kesilmis)
    - bot CALISIRKEN yapilan her degisiklik -- ozetler bastan hesaplansa
      bile. Yazici zincirin ucunu kendi hafizasinda tutar ve bir sonraki
      satiri ona baglar; dosyadaki uc tutmazsa o satir kirik cikar.
    - calisirken dosyanin yerine yenisinin konmasi ya da silinmesi:
      yazici bunu fark eder, dosyayi yeniden acar ve olayi ize yazar
      (denetim_dosyasi_yeniden_acildi).

DOSYA TEK BASINA NEYI YAKALAYAMAZ
    Bot DURURKEN dosyaya yazabilen biri, degistirdigi noktadan sonraki
    TUM satirlarin ozetini yeniden hesaplarsa -- ya da son satirlari
    silip dosyayi oyle birakirsa -- dosya kendi icinde tutarli gorunur:
    yeniden baslayan yazicinin hafizasi yoktur, diskte ne bulursa ona
    inanir. Gizli bir anahtar bunu cozmez: anahtar ayni makinede durur.

IKINCI TANIK
    Yaziciya disaridan bir "tanik" verilebilir: her halkayi ayrica
    saklayan bagimsiz bir kopya (vasi'de PostgreSQL, audit_store.py).
    Bu modul tanigin NE oldugunu bilmez; yalnizca su uc metodu cagirir:

        son_halka()                -> (sira, ozet) ya da None
        kaydet(sira, ozet, govde)  -> "yazildi" | "ayni" | "catal" | "tablo_yok"
        halkalar()                 -> [(sira, ozet, govde, zaman), ...]

    Tanik, yazicinin hafizasini yeniden baslatmadan sag cikarir: dosya
    tanigin gerisindeyse ya da ucu tutmuyorsa zincir TANIGIN ucundan
    surdurulur ve bu olay ize yazilir (denetim_dosyasi_tanikla_uyusmuyor).
    Bir sonraki satir, dosyanin kendi dogrulayicisinda da kirik cikar.
    karsilastir() iki kopyayi halka halka yan yana koyar.

    Tanik da ayni makinede: dosyaya VE veritabanina birlikte yazabilen
    biri ikisini birlikte yeniden yazabilir. Cita yukselir, kapanmaz.
    Ekim 2026'dan beri bot o kisi degil: tanikta yalnizca ekleme yetkisi
    var (audit_store.yetki_durumu). Tablo yoksa tanik "tablo_yok" der ve
    yazici onu yeniden kurdurmaz; halkalar tablo donene kadar bekler.

ROTASYON
    Dosya sinira ulasinca doner; en eski yedek silinir. Silinen basi
    silmeden ayiran tek sey, rotasyonun kendi izidir: her yeni dosya bir
    donme kaydiyla baslar (denetim_dosyasi_dondu | onceki_son_sira=N
    onceki_ozet=...). Dosyalarin basindaki eksiklik ancak boyle bir
    kayitla basliyorsa rotasyondur. Kac dosyanin gitmis olmasi GEREKTIGINI
    dosya bilemez: butun bir eski dosyanin silinmesini ancak tanik, kendi
    kopyasindaki donme kayitlarini sayarak gorur (karsilastir, yedek_sayisi).
    En eski yedegi ise yalnizca bir sonraki rotasyona kadar: o dosya o
    rotasyonda zaten silinecekti; sonrasinda diskteki durum mesru
    rotasyonunkiyle AYNIDIR (test_SINIR_en_eski_yedegi_erken_silmek_...).
    Tanik o satirlari yine de saklar. Yedek sayisi sonradan ARTIRILIRSA,
    yeni yedekler dolana kadar tanik eski dosyalari 'dosyada yok' sayar:
    bir kez onaylanir ya da kendiliginden kalkar.

BAGIMSIZ INCELEMENIN BULDUGU DORT ACIK (4 Ekim 2026) ve kapanislari
    1) Tanik tek komutla sifirlanabiliyordu (DROP TABLE) ve bot bos
       taniği "ilk kurulum" saniyordu. Artik tanigin dogum kaydi dosyada:
       tanik ilk kez dolarken zincire 'denetim_tanigi_baslangici
       ilk_sira=N' yazilir. Tanik sonradan bos ya da gec baslayan
       bulunursa bu ize alarm olarak yazilir; karsilastirma da o
       halkalari 'tanıktan önce' degil 'tanıksız' sayar.
    2) Onay bir sira ARALIGINI onayliyordu. Artik onay satiri onaylanan
       bulgularin kimliklerini tasir (onay=...); yalnizca onlar onayli
       sayilir. Onaydan sonra eski bir satira dokunmak YENI bir bulgudur.
    3) Dosyanin basindan silinen satirlar "rotasyon" sayiliyordu.
       Ilk duzeltme donmus dosyalari SAYIYORDU; ikinci inceleme bunu da
       kirdi (asagida). Artik: bkz. ROTASYON.
    4) Tanik kapaliyken yazilan halkalar taniga hic yazilmiyordu. Artik
       yazici onlari bellekte tutar ve tanik donunce -- en gec kapanirken
       -- yazar; bunu da ize kaydeder (denetim_tanigi_tamamlandi).
       Acilista dosyada tanikta olmayan fazlalik bulunursa KENDILIGINDEN
       yazilmaz: bot dururken eklenmis sahte satiri aklamak olurdu.

IKINCI BAGIMSIZ INCELEME (5 Ekim 2026): duzeltmelerin kendisi kirildi
    - Bes BOS sahte donmus dosya, bastan silmeyi "rotasyon" diye akliyordu;
      bot, tanik ve bu komut satiri ucu de yesildi. Artik donme kaydi sart.
    - Tanik bir kez sifirlaninca HER acilis yeni bir alarm yaziyordu. Artik
      alarmla birlikte yeni bir dogum kaydi yazilir; hizalama en son
      dogumla yapilir, karsilastirma en eskisiyle.
    - Yazicinin kendi kayitlari bir sonraki olayi bekliyordu. Artik
      yazdigi anda, en gec kapanirken yazilir.
    Kodla kapanmayanlar (ayni makinenin sinirlari): dosyayi VE tanigi
    birlikte eski bir haline donduren (dosyayi tanik oncesine kesip tabloyu
    silen) biri yakalanmaz -- ilk kurulumdan ayirt edilemez. Onay satiri
    anahtarsizdir: bu komut satiri (yalnizca dosyayi gorur) sahte bir onayi
    ayirt edemez, bot tanikla eder; ikisine birden yazabilen biri onay da
    uydurabilir.

AYRI HESAP (Ekim 2026, "Gunlukler Yalan Soyleyebilir mi?" sonrasi)
    Videodaki dort denemenin ikisi botun veritabani yetkisiyle yapildi:
    tanik tablosunu dusurmek ve yalnizca-ekleme kuralini kapatip satir
    silmek. Bot artik super kullanici degil; tanigin sahibi giris yapamayan
    ayri bir hesap, botun yetkisi yalnizca ekleme ve okuma. Botu ele
    geciren biri bu iki adimi atamaz. Makinenin ve veritabaninin super
    kullanicisina erisen biri hala atabilir: bkz. test_SINIR_super_kullanici_...
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASLANGIC = "0" * 32
OZET_UZUNLUGU = 32          # 128 bit: kasitli bir carpisma pratikte imkansiz,
                            # satir terminalde okunur kalir.
_HALKA = re.compile(
    r"^(?P<govde>.*\| sira=(?P<sira>\d+)) \| ozet=(?P<ozet>[0-9a-f]{32})$"
)
_AUDIT = "AUDIT |"

# Yazicinin kendi gozlemleri -- ize, zincirin parcasi olarak yazilir:
MUDAHALE_OLAYI = "denetim_dosyasi_yeniden_acildi"     # calisirken dosyaya dokunuldu
TANIK_OLAYI = "denetim_dosyasi_tanikla_uyusmuyor"     # dururken dokunuldu; tanik gordu
# Bilgi kayitlari (bulgu DEGIL): tanigin dogumu ve kesintiden sonra tamamlanmasi.
TANIK_BASLANGICI = "denetim_tanigi_baslangici"       # ilk_sira=N: tanik bu halkadan beri tutuyor
TANIK_TAMAMLAMA = "denetim_tanigi_tamamlandi"        # kesintide yazilanlar taniga sonradan yazildi
# Rotasyon da zincirde iz birakir: her yeni dosyanin ILK satiri.
#     onceki_son_sira=N onceki_ozet=<ozet> [tanik_ilk_sira=M]
# Dosyalarin basindaki eksiklik ancak boyle bir kayitla basliyorsa
# rotasyondur. Kayit bir onceki halkanin ozetini de tasir: dosyanin ilk
# satiri olsa bile kendi ozeti dogrulanabilir -- baska bir satirin govdesi
# donme kaydina cevrilip ozeti oldugu gibi birakilamaz. tanik_ilk_sira:
# yazicinin bildigi tanik dogumu; dogum kaydi eski dosyayla birlikte
# gidince de tanigin silinmesi gorulebilsin.
ROTASYON_OLAYI = "denetim_dosyasi_dondu"
# Insanin "gordum, inceledim" kaydi:
#     kapsam=N bulgu=M onay=<kimlik>,<kimlik>,...
# kapsam: onay istendigi anda zincirin son halkasi. onay: onaylanan
# bulgularin kimlikleri -- YALNIZCA bunlar onayli sayilir. Onay da bir
# halka: zincire bagli, taniga yazili. Gecerli bir halka degilse hicbir
# seyi onaylamaz. Kimlik listesi olmayan eski bicim onay artik gecmez:
# bir araligi onayliyordu ve araliktaki yeni bir mudahaleyi yutuyordu.
ONAY_OLAYI = "iz_onaylandi"
KIMLIK_UZUNLUGU = 16        # 64 bit: belli bir kimlige denk gelen satir uretmek pratikte imkansiz
_ONAY = re.compile(
    r"AUDIT \| " + ONAY_OLAYI + r" \| user=[^|]* \| kapsam=(?P<kapsam>\d+)"
    r"(?: bulgu=\d+)?(?: onay=(?P<onay>[0-9a-f]{16}(?:,[0-9a-f]{16})*))?"
)
_TANIK_BAS = re.compile(
    r"AUDIT \| " + TANIK_BASLANGICI + r" \| user=[^|]* \| ilk_sira=(?P<ilk>\d+)"
)
_ROTASYON = re.compile(
    r"AUDIT \| " + ROTASYON_OLAYI + r" \| user=[^|]* \| onceki_son_sira=(?P<son>\d+)"
    r" onceki_ozet=(?P<ozet>[0-9a-f]{32})(?: tanik_ilk_sira=(?P<tanik>\d+))?"
)
_MUDAHALE = re.compile(
    r"AUDIT \| (?P<olay>" + MUDAHALE_OLAYI + "|" + TANIK_OLAYI + r") \| "
    r"user=[^|]* \| (?P<sebep>[^|]+?) \| sira=\d+$"
)
TABLO_YOK_SONUCU = "tablo_yok"   # tanik.kaydet(): tablo yok, yazilamadi (audit_store)
_KUYRUK_SINIRI = 10000      # kesintide bellekte tutulacak en fazla halka

_log = logging.getLogger("audit_chain")


def ozet(onceki: str, govde: str) -> str:
    return hashlib.sha256(f"{onceki}\n{govde}".encode("utf-8")).hexdigest()[:OZET_UZUNLUGU]


def bulgu_kimligi(*parcalar) -> str:
    """Bir bulgunun kimligi: turu, yeri, aciklamasi ve satirin KENDISI.

    Konum (dosya:satir) kimlige girmez -- ustteki bir satir silinince
    kayar. Satirin icerigi girer: onaylanmis bir bulgunun satirina
    sonradan yeniden dokunulursa kimlik degisir ve bulgu yeniden uyarir.
    """
    metin = "\x1f".join("" if p is None else str(p) for p in parcalar)
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:KIMLIK_UZUNLUGU]


def halka_coz(satir: str):
    """(govde, sira, ozet) ya da None -- zincirli bir satir degilse."""
    m = _HALKA.match(satir.rstrip("\r\n"))
    if not m:
        return None
    return m.group("govde"), int(m.group("sira")), m.group("ozet")


# ── Yazici ───────────────────────────────────────────────────────────────────

def son_halka(yol) -> tuple[int, str]:
    """Dosyadaki son saglam halkanin (sira, ozet) degeri.

    Yalnizca dosyanin sonu okunur. Ana dosyada zincirli satir yoksa
    (yeni donmus ya da zincirden once yazilmis), bir onceki yedege
    bakilir. Hic yoksa (0, BASLANGIC).
    """
    yol = Path(yol)
    for aday in (yol, Path(f"{yol}.1")):
        if not aday.exists():
            continue
        with open(aday, "rb") as f:
            f.seek(0, 2)
            boyut = f.tell()
            f.seek(max(0, boyut - 65536))
            kuyruk = f.read().decode("utf-8", errors="replace")
        for satir in reversed(kuyruk.splitlines()):
            h = halka_coz(satir)
            if h:
                return h[1], h[2]
    return 0, BASLANGIC


class ZincirliDosyaYazicisi(RotatingFileHandler):
    """Her satira sira ve ozet ekleyen donen dosya yazicisi.

    emit() bastan yazildi, format() degil: RotatingFileHandler format()'i
    satir basina IKI kez cagiriyor (donme kontrolu icin bir, yazma icin
    bir). Zincir durumu orada ilerleseydi her satir iki halka yerdi.
    Kilit: logging.Handler.handle() emit'i kendi kilidiyle sarar, yani
    ayni anda yazan iki is parcacigi zinciri catallayamaz.
    """

    def __init__(self, filename, tanik=None, **kwargs):
        self._uyari_veriliyor = False
        self.tanik = None
        self.tanik_durumu = None    # son tanik sorunu (saglik raporu icin); None = yok
        self._tanik_kesik = False   # erisim sorunu suruyor mu (uyari bir kez verilsin)
        self._hizalandi = False
        self._bekleyen = []         # ilk yazimda ize dusulecek tanik BULGULARI: (sebep, sonra)
        self._bilgi_bekleyen = []   # ilk yazimda ize dusulecek BILGI kayitlari: (olay, ayrinti)
        self._tanik_baslangici = None   # dosyaya gore tanigin ilk halkasi (dogum kaydi)
        self._sifirlama_bildirildi = False
        self._tanik_kuyrugu = []    # tanik kapaliyken yazilan halkalar: (sira, ozet, govde)
        self._kuyruk_tasti = False
        self._son_kayit_adi = None  # kapanista bekleyen kayitlari yazmak icin (logger adi)
        super().__init__(filename, **kwargs)
        # Zincirin ucu DISKTEN yalnizca burada, acilista okunur. Sonrasinda
        # esas olan yazicinin kendi hafizasidir: ne yazdigini bilen odur.
        self.son_sira, self.son_ozet = son_halka(self.baseFilename)
        self._satir_sonu_garanti()
        if tanik is not None:
            self.tanik_bagla(tanik)

    # -- Ikinci tanik -----------------------------------------------------------
    #
    # Yeniden baslayan yazicinin hafizasi yok; tanigin var. Acilista
    # dosyanin ucu tanikla karsilastirilir:
    #
    #   tanik ileride        -> dosyadan satir silinmis (bot dururken):
    #                           zincir TANIGIN ucundan surer, olay ize yazilir
    #   ayni sira, ozet farkli -> dosya bastan hesaplanmis: ayni sekilde
    #   dosya ileride        -> tanik bazi halkalari kacirmis (veritabani
    #                           kapaliydi): dosyadan surer, karsilastirma soyler
    #
    # Tanik okunamazsa bot DURMAZ (Raporla, durdurma): zincir dosyadan
    # surer ve hizalama ilk yazimda yeniden denenir -- veritabani botla
    # ayni anda ayaga kalkiyor, ilk saniyelerde hazir olmayabilir.

    def tanik_bagla(self, tanik):
        self.acquire()
        try:
            self.tanik = tanik
            self._hizalandi = False
            # Tanigin dogum kaydi DOSYADAN okunur: tanik silinmisse kendi
            # gecmisini de goturmustur. Dosyanin tamami yalnizca burada,
            # acilista okunur. Hizalama EN SON dogumla yapilir: sifirlanip
            # yeniden dogan tanigin ilk halkasi oradadir. (Karsilastirma ise
            # en eskisine bakar: o gunden beri eksik olan, onaylanana kadar
            # gorunur.)
            self._tanik_baslangici = dogrula_dosyalar(
                dosyalari_sirala(self.baseFilename)).son_tanik_dogumu
            self._tanikla_hizala()
        finally:
            self.release()

    def _tanik_ilk_sira(self):
        """Tanigin en eski halkasi. ilk_sira() olmayan tanik da kabul edilir."""
        ilk_sira = getattr(self.tanik, "ilk_sira", None)
        if ilk_sira is not None:
            return ilk_sira()
        halkalar = self.tanik.halkalar()
        return halkalar[0][0] if halkalar else None

    def _sifirlama_bildir(self, sebep: str, yeni_ilk: int):
        """Tanigin gecmisi gitmis: BULGU olarak ize yazilir, tek bir kez.

        Tanik bundan sonrasini yeniden tutar ve bu da YENI bir dogum kaydi
        olarak yazilir (ilk_sira = yeni tanigin ilk halkasi). Yazilmasaydi
        her acilis ayni sifirlamayi yeniden bildirirdi; onay bunu
        susturamazdi ve gercek bir ikinci sifirlama o gurultude kaybolurdu.
        """
        self._sifirlama_bildirildi = True
        self._tanik_baslangici = yeni_ilk
        self._bekleyen.append((sebep, "Tanık bundan sonrasını yeniden tutuyor"))
        self._bilgi_bekleyen.append((TANIK_BASLANGICI, f"ilk_sira={yeni_ilk}"))
        _log.warning(f"⚠️ Denetim izi: {sebep}.")

    def _siradaki_tanik_halkasi(self) -> int:
        """Taniga yazilacak ilk halka: kesintide bekleyen varsa onlarin ilki."""
        return self._tanik_kuyrugu[0][0] if self._tanik_kuyrugu else self.son_sira + 1

    def _tanik_erisilemedi(self, ne: str, hata: Exception):
        """Erisim sorunu: uyari KESINTININ basinda bir kez verilir, her yazimda degil."""
        # Veritabani hatalari cok satirli olabilir; saglik satiri tek satir.
        metin = " ".join(str(hata).split())[:160]
        if not self._tanik_kesik:
            _log.warning(f"⚠️ Denetim izi: {ne} ({metin}); dosyaya yazmaya devam ediliyor.")
        self._tanik_kesik = True
        self.tanik_durumu = f"{ne}: {metin}"

    def _tanik_erisildi(self):
        if self._tanik_kesik:
            _log.info("✅ Denetim izi: tanığa yeniden erişildi.")
            self.tanik_durumu = None    # catallanma gibi bulgular kalir; yalnizca kesinti kalkar
        self._tanik_kesik = False

    def _tanikla_hizala(self):
        try:
            uc = self.tanik.son_halka()
            ilk = self._tanik_ilk_sira() if uc is not None else None
        except Exception as e:
            self._tanik_erisilemedi("tanık okunamadı", e)
            return
        self._hizalandi = True
        self._tanik_erisildi()
        bas = self._tanik_baslangici
        if uc is None:
            if bas is not None:
                # Dosya tanigin dogdugunu hatirliyor; tanik bos. Ilk kurulum
                # DEGIL: tablo silinmis ya da bosaltilmis.
                self._sifirlama_bildir(
                    f"tanık boş, ama dosyadaki doğum kaydına göre sıra {bas} itibarıyla "
                    f"tutuluyordu: tanık sıfırlanmış",
                    yeni_ilk=self._siradaki_tanik_halkasi())
            else:
                # Gercek ilk kurulum: dogum kaydi, taniga yazilan ilk halka olur.
                self._bilgi_bekleyen.append((TANIK_BASLANGICI, None))
            return
        if bas is None:
            # Bu duzeltmeden once kurulmus tanik: dogum kaydini simdi yaz.
            self._tanik_baslangici = ilk
            self._bilgi_bekleyen.append((TANIK_BASLANGICI, f"ilk_sira={ilk}"))
        elif ilk is not None and ilk > bas:
            self._sifirlama_bildir(
                f"tanığın ilk halkası sıra {ilk}, doğum kaydına göre sıra {bas} olmalı: "
                f"tanığın başından halka silinmiş", yeni_ilk=ilk)
        t_sira, t_ozet = uc
        if t_sira > self.son_sira:
            sebep = (f"dosya tanığın gerisinde: dosyanın son halkası sıra {self.son_sira}, "
                     f"tanığınki sıra {t_sira}")
        elif t_sira == self.son_sira and t_ozet != self.son_ozet:
            sebep = f"dosyanın son halkası tanıkla uyuşmuyor: sıra {t_sira}"
        else:
            # Dosya tanigin ILERISINDEYSE (tanik bazi halkalari kacirmis) o
            # halkalar taniga KENDILIGINDEN yazilmaz: bot dururken dosyanin
            # sonuna eklenmis, ozeti dogru hesaplanmis bir sahte satir da
            # boyle gorunur. Karsilastirma onlari 'tanıksız' diye gosterir.
            return
        self.son_sira, self.son_ozet = t_sira, t_ozet    # tanigin ucundan surdur
        self._bekleyen.append((sebep, "Zincir tanığın son halkasından sürdürüldü"))
        _log.warning(f"⚠️ Denetim izi: {sebep}. Zincir tanığın son halkasından sürdürülecek.")

    def _tanige_yaz(self, sira: int, oz: str, govde: str):
        """Dosyaya yazilan halkayi taniga da yazar. Hata botu durdurmaz.

        Tanik kapaliyken yazilan halkalar bellekte bekler; tanik donunce
        sirayla, bu halkadan ONCE yazilir. Yazici yalnizca KENDI yazdigini
        tamamlar -- dosyada buldugunu degil.
        """
        if self._tanik_kuyrugu and not self._kuyrugu_bosalt():
            self._kuyruga_ekle(sira, oz, govde)
            return
        try:
            sonuc = self.tanik.kaydet(sira, oz, govde)
        except Exception as e:
            self._tanik_erisilemedi(f"tanığa yazılamadı (sıra {sira})", e)
            self._kuyruga_ekle(sira, oz, govde)
            return
        if sonuc == TABLO_YOK_SONUCU:
            self._tablo_yok(sira)
            self._kuyruga_ekle(sira, oz, govde)
            return
        self._tanik_erisildi()
        self._kaydedildi(sira, sonuc)

    def _tablo_yok(self, sira: int):
        """Tanigin tablosu yok. Bot onu yeniden kurmaz (kuramaz): halkalar
        bellekte bekler, tablo kurulum betigiyle donunce sirayla yazilir.

        Tanik daha once tutulmaya baslamissa bu ilk kurulum DEGIL: tablo
        silinmis. Bulgu bir kez yazilir; yeni tanigin ilk halkasi, bekleyen
        ilk halka (sira) olur -- tablo dondugunde oradan dolar.
        """
        self._tanik_erisilemedi(
            f"tanığa yazılamadı (sıra {sira})",
            Exception("tanık tablosu yok; bot onu yeniden kuramaz, kurulum betiği gerekli"))
        bas = self._tanik_baslangici
        if bas is not None and sira > bas and not self._sifirlama_bildirildi:
            self._sifirlama_bildir(
                f"tanık tablosu yok: sıra {bas}–{sira - 1} tanıkta kayıtlıydı, tablo silinmiş; "
                f"tanık sıfırlanmış", yeni_ilk=sira)

    def _kaydedildi(self, sira: int, sonuc: str):
        if sonuc == "yazildi":
            self._sifirlama_bildirildi = False      # bir sonraki silinme yine bildirilsin
        if sonuc == "catal":
            self.tanik_durumu = f"çatallanma: sıra {sira} tanıkta başka bir özetle kayıtlı"
            _log.warning(f"⚠️ Denetim izi: {self.tanik_durumu}.")

    def _kuyruga_ekle(self, sira: int, oz: str, govde: str):
        if len(self._tanik_kuyrugu) < _KUYRUK_SINIRI:
            self._tanik_kuyrugu.append((sira, oz, govde))
        else:
            self._kuyruk_tasti = True

    def _kuyrugu_bosalt(self) -> bool:
        """Kesintide yazilanlari taniga yazar. Tanik hala kapaliysa False."""
        ilk = son = self._tanik_kuyrugu[0][0]
        while self._tanik_kuyrugu:
            sira, oz, govde = self._tanik_kuyrugu[0]
            try:
                sonuc = self.tanik.kaydet(sira, oz, govde)
            except Exception as e:
                self._tanik_erisilemedi(f"tanığa yazılamadı (sıra {sira})", e)
                return False
            if sonuc == TABLO_YOK_SONUCU:
                self._tablo_yok(sira)
                return False
            self._tanik_kuyrugu.pop(0)
            self._tanik_erisildi()
            self._kaydedildi(sira, sonuc)
            son = sira
        tasti = "; kuyruk taştı, bazı halkalar tanıksız kaldı" if self._kuyruk_tasti else ""
        self._kuyruk_tasti = False
        aralik_ = f"sıra {ilk}" if ilk == son else f"sıra {ilk}–{son}"
        self._bilgi_bekleyen.append(
            (TANIK_TAMAMLAMA, f"kesinti: {aralik_} tanığa sonradan yazıldı{tasti}"))
        return True

    def close(self):
        """Kapanirken: tanik dondu ama bot bir sey yazmadan duruyorsa,
        kesintide yazilanlar yine de taniga gecsin; yazicinin bekleyen kendi
        kayitlari (orn. 'tanik tamamlandi') da ize dussun. Kapanis hicbir
        kosulda patlamaz."""
        self.acquire()
        try:
            if self.tanik is not None and self._tanik_kuyrugu:
                try:
                    self._kuyrugu_bosalt()
                except Exception:
                    pass
            # Yalnizca bu calismada bir sey yazildiysa: hic yazmamis bir
            # yazicinin bekleyenleri bir sonraki acilista yeniden bulunur.
            if (self._bekleyen or self._bilgi_bekleyen) and self._son_kayit_adi is not None \
                    and self.stream is not None:
                try:
                    kayit = logging.LogRecord(self._son_kayit_adi, logging.INFO,
                                              __file__, 0, "", None, None)
                    sebep = self._degistiyse_yeniden_ac()
                    self._bekleyenleri_yaz(kayit)
                    if sebep:
                        self._bildirim_yaz(kayit, MUDAHALE_OLAYI, sebep, "Dosya yeniden açıldı")
                except Exception:
                    pass
        finally:
            self.release()
        super().close()

    # -- Dosya disaridan degistirilirse --------------------------------------
    #
    # Cogu editor (TextEdit, sed -i, vim) kaydederken YENI bir dosya
    # yazip eskisinin yerine koyar. Yazici eski dosyayi acik tuttugu
    # surece sonraki satirlar artik hicbir yerde gorunmeyen eski dosyaya
    # gider: iz, yeniden baslatmaya kadar SESSIZCE kaydetmeyi birakir.
    # Her yazimdan once diskteki dosyanin kimligi (aygit, inode) acik
    # akisinkiyle karsilastirilir; farkliysa yeniden acilir -- ve bu
    # olay izin KENDISINE yazilir.
    #
    # Yeniden acinca zincirin ucu diskten OKUNMAZ. Okunsaydi, son
    # satirlari silip dosyayi geri koyan birinin istedigi uc kabul
    # edilir, iz silinenin ustunden sorunsuzca devam ederdi. Hafizadaki
    # uca baglanan bir sonraki satir, diskteki uc tutmuyorsa kirik cikar.

    def _satir_sonu_garanti(self):
        """Dosya yarim bir satirla bitiyorsa yeni satir yeni satirda baslasin."""
        try:
            with open(self.baseFilename, "rb") as f:
                f.seek(0, 2)
                if f.tell() == 0:
                    return
                f.seek(-1, 2)
                son_bayt = f.read(1)
        except FileNotFoundError:
            return
        if son_bayt != b"\n":
            if self.stream is None:
                self.stream = self._open()
            self.stream.write(self.terminator)
            self.flush()

    def _degistiyse_yeniden_ac(self):
        """Disaridan degistirildiyse yeniden acar ve sebebini dondurur."""
        if self.stream is None:
            return None
        try:
            disk = os.stat(self.baseFilename)
            disk_kimligi = (disk.st_dev, disk.st_ino)
        except FileNotFoundError:
            disk_kimligi = None
        akis = os.fstat(self.stream.fileno())
        if disk_kimligi == (akis.st_dev, akis.st_ino):
            return None
        sebep = ("dosya silinmiş ya da taşınmış" if disk_kimligi is None
                 else "dosya dışarıdan değiştirilmiş (yerine yenisi konmuş)")
        # Once yenisi: acilamazsa eskisi yerinde kalir, hata yuksek sesle
        # raporlanir (handleError) ve bir sonraki yazimda yeniden denenir.
        yeni = self._open()
        self.stream.close()
        self.stream = yeni
        self._satir_sonu_garanti()
        return sebep

    def _sistem_satiri(self, record, seviye: int, olay: str, ayrinti) -> str:
        """Yazicinin kendi kaydi, botun satir bicimiyle (user=sistem)."""
        ek = logging.LogRecord(
            record.name, seviye, record.pathname, record.lineno,
            f"AUDIT | {olay} | user=sistem | {ayrinti}", None, None,
        )
        # Fark edildigi an, onu tetikleyen yazimin anidir. Kendi saati
        # olsaydi, kendisinden SONRA gelen satirdan 1 ms ileride dururdu.
        ek.created, ek.msecs = record.created, record.msecs
        return self.format(ek)

    def _bildirim_yaz(self, record, olay: str, sebep: str, sonra: str):
        """Yazicinin gozlemini ize yazar (zincirin parcasi olarak) ve genel loga uyarir."""
        self._zincire_yaz(self._sistem_satiri(record, logging.WARNING, olay, sebep), record)
        # Uyari ayni logger'dan cikar, yani bu yaziciya da ugrar: kilit
        # ayni is parcacigina yeniden girmeye izin verir. Bayrak olmasa
        # uyari, filtresi olmayan bir kurulumda zincire ikinci satir
        # olarak duserdi. Bot filtre kullaniyor; yazici ona guvenmiyor.
        self._uyari_veriliyor = True
        try:
            logging.getLogger(record.name).warning(
                f"⚠️ Denetim izi: {sebep}. {sonra}; olay ize "
                f"sıra {self.son_sira} olarak yazıldı."
            )
        finally:
            self._uyari_veriliyor = False

    def _bilgi_yaz(self, record, olay: str, ayrinti):
        """Yazicinin BILGI kaydi (bulgu degil): zincire yazilir, uyari vermez."""
        if olay == TANIK_BASLANGICI and ayrinti is None:
            # Tanigin ilk halkasi: kesintide bekleyen varsa onlarin ilki (bu
            # kayittan once taniga gececekler), yoksa bu kaydin kendisi.
            ilk = self._siradaki_tanik_halkasi()
            ayrinti = f"ilk_sira={ilk}"
            self._tanik_baslangici = ilk
        self._zincire_yaz(self._sistem_satiri(record, logging.INFO, olay, ayrinti), record)
        _log.info(f"Denetim izi: {olay} · {ayrinti} (sıra {self.son_sira})")

    def _bekleyenleri_yaz(self, record):
        """Bekleyen kendi kayitlari. Bulgular once, bilgiler sonra. Yazarken
        yenileri dogabilir (orn. kesinti tamamlaninca): liste bosalana kadar."""
        while self._bekleyen or self._bilgi_bekleyen:
            if self._bekleyen:
                sebep_t, sonra = self._bekleyen.pop(0)
                self._bildirim_yaz(record, TANIK_OLAYI, sebep_t, sonra)
            else:
                olay, ayrinti = self._bilgi_bekleyen.pop(0)
                self._bilgi_yaz(record, olay, ayrinti)

    # -- Yazma ----------------------------------------------------------------
    #
    # ROTASYON IZ BIRAKIR. Dosya sinira ulasinca doner; yeni dosyanin ilk
    # satiri bir donme kaydidir. Eskiden dogrulayici, dosyalarin basindaki
    # bir eksikligi ortada donmus dosya var diye "rotasyon" sayiyordu: bes
    # bos sahte dosya koymak, bastan silmeyi aklamaya yetiyordu (ikinci
    # bagimsiz inceleme, 5 Ekim). Artik eksiklik ancak dosyalar gecerli bir
    # donme kaydiyla basliyorsa rotasyondur; tanik da kendi kopyasindaki
    # donme kayitlarini sayar.

    def _donmeli(self, ham: str) -> bool:
        if self.maxBytes <= 0 or self.backupCount <= 0:
            return False                         # RotatingFileHandler gibi: donme yok
        self.stream.seek(0, 2)
        konum = self.stream.tell()
        uzunluk = len(f"{ham} | sira={self.son_sira + 1} | ozet={BASLANGIC}"
                      f"{self.terminator}".encode("utf-8"))
        return konum > 0 and konum + uzunluk >= self.maxBytes

    def _zincire_yaz(self, ham: str, record):
        ham = ham.replace("\r", " ").replace("\n", " ")
        if self._donmeli(ham):
            onceki_son, onceki_ozet = self.son_sira, self.son_ozet
            self.doRollover()
            if self.stream is None:              # delay=True ise doRollover acmaz
                self.stream = self._open()
            ayrinti = f"onceki_son_sira={onceki_son} onceki_ozet={onceki_ozet}"
            if self._tanik_baslangici is not None:
                ayrinti += f" tanik_ilk_sira={self._tanik_baslangici}"
            self._halka_yaz(self._sistem_satiri(record, logging.INFO, ROTASYON_OLAYI, ayrinti))
        self._halka_yaz(ham)

    def _halka_yaz(self, ham: str):
        ham = ham.replace("\r", " ").replace("\n", " ")
        sira = self.son_sira + 1
        govde = f"{ham} | sira={sira}"
        oz = ozet(self.son_ozet, govde)
        self.stream.write(f"{govde} | ozet={oz}{self.terminator}")
        self.flush()
        self.son_sira, self.son_ozet = sira, oz
        # Tanik, dosyaya yazildiktan SONRA: dosyaya yazilamayan bir halka
        # tanikta da olmamali.
        if self.tanik is not None:
            self._tanige_yaz(sira, oz, govde)

    def emit(self, record):
        if self._uyari_veriliyor:
            return
        try:
            self._son_kayit_adi = record.name
            if self.stream is None:
                self.stream = self._open()
            # Once dogru dosyaya yazdigimizdan emin ol; sonra bildirimler.
            sebep = self._degistiyse_yeniden_ac()
            if self.tanik is not None and not self._hizalandi:
                self._tanikla_hizala()
            self._bekleyenleri_yaz(record)
            if sebep:
                self._bildirim_yaz(record, MUDAHALE_OLAYI, sebep, "Dosya yeniden açıldı")
            self._zincire_yaz(self.format(record), record)
            # Bu yazim sirasinda doganlar (kesinti tamamlandi, calisirken
            # silinen tanik) bir sonraki olayi beklemesin: o olay hic
            # gelmeyebilir.
            self._bekleyenleri_yaz(record)
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


# ── Dogrulayici ──────────────────────────────────────────────────────────────

@dataclass
class Sorun:
    konum: str
    sira: int | None
    tur: str            # degistirilmis | eksik | eklenmis | zincirsiz | yarim | yabanci
                        # | mudahale (yazicinin kendi kaydettigi dis mudahale)
    aciklama: str
    sonra: int | None = None    # sira'siz bulgu: kendisinden onceki son gecerli halka
    kimlik: str = ""            # bulgu_kimligi(): onay bunu listeler


def _sorun(konum, sira, tur, aciklama, satir, sonra=None) -> Sorun:
    return Sorun(konum, sira, tur, aciklama, sonra,
                 bulgu_kimligi(tur, sira, sonra, aciklama, satir))


@dataclass
class Rapor:
    halka: int = 0
    zincir_oncesi: int = 0
    baslangic_eksik: tuple | None = None
    bas_rotasyon: bool = True       # baslangic eksikligi rotasyon olabilir mi
    son_sira: int = 0
    son_ozet: str = BASLANGIC
    sorunlar: list = field(default_factory=list)
    mudahaleler: list = field(default_factory=list)
    halkalar: list = field(default_factory=list)    # (sira, ozet, konum, govde) -- tanik icin
    onay: tuple | None = None                       # (sira, kapsam, konum): en genis gecerli onay
    onaylar: list = field(default_factory=list)     # gecerli onaylar: (sira, kapsam, konum, kimlikler)
    eski_onaylar: list = field(default_factory=list)  # kimlik listesiz eski onaylar: (sira, konum)
    onaylanan: list = field(default_factory=list)   # onaylanmis bulgular -- silinmez, gosterilir
    tanik_baslangici: int | None = None             # tanigin EN ESKI dogumu (ilk_sira): karsilastirma siniri
    son_tanik_dogumu: int | None = None             # tanigin EN SON dogumu: yazicinin hizalamasi

    @property
    def saglam(self) -> bool:
        """Zincir kendi icinde tutarli mi (onaylanmamis kirik yok)."""
        return not self.sorunlar

    @property
    def temiz(self) -> bool:
        """Tutarli VE yazici calisirken hicbir dis mudahale kaydetmemis.

        Ayri tutuldu, cunku ikisi farkli seyler soyler: icerigi
        degistirmeden kaydedilen bir dosya zinciri bozmaz, ama dosyaya
        dokunuldugu yine de bir denetim olayidir.
        """
        return self.saglam and not self.mudahaleler


def dosyalari_sirala(yol) -> list:
    """Donmus yedekler dahil, eskiden yeniye: yol.N ... yol.1, yol."""
    yol = Path(yol)
    yedekler = []
    for aday in yol.parent.glob(yol.name + ".*"):
        son_ek = aday.name[len(yol.name) + 1:]
        if son_ek.isdigit():
            yedekler.append((int(son_ek), aday))
    sirali = [p for _, p in sorted(yedekler, reverse=True)]
    if yol.exists():
        sirali.append(yol)
    return sirali


def _dogum(r: Rapor, ilk: int):
    if r.tanik_baslangici is None or ilk < r.tanik_baslangici:
        r.tanik_baslangici = ilk
    if r.son_tanik_dogumu is None or ilk > r.son_tanik_dogumu:
        r.son_tanik_dogumu = ilk


def dogrula(satirlar, rotasyon_olabilir: bool = True, bas_serbest: bool = False) -> Rapor:
    """satirlar: (konum, satir) ikilileri, eskiden yeniye.

    Okunan ilk halka 1 degilse zincirin basi eksiktir. Bu ancak uc kosulla
    rotasyondur: rotasyon_olabilir (donmus dosya var -- cagiran bilir),
    zincirden onceki satirlar ortada yok (rotasyon en eski satirlari ONCE
    goturur) ve ilk halka gecerli bir donme kaydi (yazici her yeni dosyayi
    onunla baslatir; kaydin ozeti, tasidigi onceki ozetle dogrulanir).
    Gerisi silmedir.

    bas_serbest: zincirin gec baslamasi olagan (tanigin kendi kopyasi:
    tanik dogdugu halkadan baslar) -- bas eksikligi bulgu sayilmaz.
    """
    r = Rapor()
    onceki_ozet = onceki_sira = None

    for konum, satir in satirlar:
        satir = satir.rstrip("\r\n")
        if not satir.strip():
            continue
        h = halka_coz(satir)

        if h is None:
            sonra = onceki_sira or 0
            if onceki_ozet is None and _AUDIT in satir and "| sira=" not in satir:
                r.zincir_oncesi += 1           # zincir kurulmadan once yazilmis
            elif "| sira=" in satir or "| ozet=" in satir:
                r.sorunlar.append(_sorun(konum, None, "yarim",
                    "yarım ya da bozulmuş halka (yazma kesilmiş ya da satır düzenlenmiş)",
                    satir, sonra))
            elif _AUDIT in satir:
                r.sorunlar.append(_sorun(konum, None, "zincirsiz",
                    "zincirsiz bir denetim satırı araya eklenmiş", satir, sonra))
            else:
                r.sorunlar.append(_sorun(konum, None, "yabanci",
                    "denetim satırı olmayan bir satır eklenmiş", satir, sonra))
            continue

        govde, sira, oz = h
        r.halka += 1
        sorun_sayisi = len(r.sorunlar)
        r.halkalar.append((sira, oz, konum, govde))
        m = _MUDAHALE.search(govde)
        if m:
            r.mudahaleler.append(_sorun(konum, sira, "mudahale", m.group("sebep"), satir))

        if onceki_ozet is None:                # okunabilen ilk halka
            if sira == 1:
                if ozet(BASLANGIC, govde) != oz:
                    r.sorunlar.append(_sorun(konum, sira, "degistirilmis",
                        "ilk halka tutmuyor: satır değiştirilmiş", satir))
            else:
                r.baslangic_eksik = (1, sira - 1)
                d = _ROTASYON.search(govde)
                donme_kaydi = (d is not None and int(d.group("son")) == sira - 1
                               and ozet(d.group("ozet"), govde) == oz)
                if not bas_serbest and (not rotasyon_olabilir or r.zincir_oncesi
                                        or not donme_kaydi):
                    r.bas_rotasyon = False
                    neden = ("zincirden önceki satırlar yerinde" if r.zincir_oncesi
                             else "dönmüş dosya yok" if not rotasyon_olabilir
                             else "ilk halka geçerli bir dönme kaydı değil")
                    eksik = "sıra 1" if sira == 2 else f"sıra 1–{sira - 1}"
                    r.sorunlar.append(_sorun(konum, sira, "eksik",
                        f"başlangıç eksik: {eksik} kayıp: satır silinmiş "
                        f"(rotasyon değil: {neden})", satir))
        elif sira == onceki_sira + 1:
            if ozet(onceki_ozet, govde) != oz:
                r.sorunlar.append(_sorun(konum, sira, "degistirilmis",
                    f"özet tutmuyor: bu satır ya da bir önceki (sıra {onceki_sira}) değiştirilmiş",
                    satir))
        elif sira > onceki_sira + 1:
            eksik = (f"sıra {onceki_sira + 1}" if sira == onceki_sira + 2
                     else f"sıra {onceki_sira + 1}–{sira - 1}")
            r.sorunlar.append(_sorun(konum, sira, "eksik",
                f"{eksik} kayıp: satır silinmiş", satir))
        else:
            r.sorunlar.append(_sorun(konum, sira, "eklenmis",
                f"sıra {sira} tekrar ediyor (önceki {onceki_sira}): araya satır eklenmiş", satir))

        gecerli = len(r.sorunlar) == sorun_sayisi
        # Onay, ancak KENDISI gecerli bir halkaysa sayilir: araya sokulmus,
        # degistirilmis ya da kendinden sonrasini kapsamaya calisan bir
        # onay hicbir seyi onaylamaz. Ve yalnizca LISTELEDIGI bulgulari.
        o = _ONAY.search(govde)
        if o and gecerli and int(o.group("kapsam")) < sira:
            kapsam = int(o.group("kapsam"))
            if o.group("onay") is None:
                r.eski_onaylar.append((sira, konum))
            else:
                r.onaylar.append((sira, kapsam, konum, frozenset(o.group("onay").split(","))))
                if r.onay is None or kapsam >= r.onay[1]:
                    r.onay = (sira, kapsam, konum)
        # Tanigin dogum kaydi. Karsilastirmanin siniri EN ESKISIDIR: sonradan
        # eklenen bir kayit tanigin baslangicini ileri alip bir silmeyi
        # gizleyemez. Yazicinin hizalamasi EN SONUNA bakar: tanik sifirlanip
        # yeniden dogduysa ilk halkasi oradadir. Donme kayitlari da dogumu
        # tasir: dogum kaydi eski dosyayla gitse de bilgi kalir.
        t = _TANIK_BAS.search(govde)
        if t and gecerli and int(t.group("ilk")) <= sira:
            _dogum(r, int(t.group("ilk")))
        d = _ROTASYON.search(govde)
        if d and gecerli and d.group("tanik") and int(d.group("tanik")) <= sira:
            _dogum(r, int(d.group("tanik")))

        onceki_ozet, onceki_sira = oz, sira    # kopmadan sonra yeniden hizala

    r.son_sira = onceki_sira or 0
    r.son_ozet = onceki_ozet or BASLANGIC
    if r.onaylar:
        _onaylananlari_ayir(r)
    return r


def _kapsamda(x: Sorun, kapsam: int) -> bool:
    """Onay istendigi anda gorulebilen bir bulgu muydu?

    Sira'li bulgular: sira <= kapsam. Sira'siz olanlar (araya sokulmus
    satir gibi): kendinden onceki gecerli halka kapsamin KESINLIKLE
    icindeyse. Kapsamin son halkasindan hemen sonra duran bir satir onay
    istendikten sonra da eklenmis olabilir; onaylanmis sayilmaz.
    """
    if x.sira is not None:
        return x.sira <= kapsam
    return (x.sonra or 0) < kapsam


def _onaylandi_mi(x: Sorun, onaylar) -> bool:
    """Bulgu, kapsamina girdigi bir onayin LISTESINDE mi?"""
    return any(x.kimlik in kimlikler and _kapsamda(x, kapsam)
               for _sira, kapsam, _konum, kimlikler in onaylar)


def _onaylananlari_ayir(r: Rapor):
    for liste in (r.sorunlar, r.mudahaleler):
        kalan = [x for x in liste if not _onaylandi_mi(x, r.onaylar)]
        r.onaylanan.extend(x for x in liste if _onaylandi_mi(x, r.onaylar))
        liste[:] = kalan
    r.onaylanan.sort(key=lambda x: x.sira if x.sira is not None else (x.sonra or 0) + 0.5)


def dogrula_dosyalar(dosyalar) -> Rapor:
    """dosyalar: dosyalari_sirala() ciktisi -- eskiden yeniye.

    Donmus dosyalari SAYMAK bir sey kanitlamaz: bos bir 'iz.log.1' koymak
    herkesin elinde. Basin eksikligini rotasyon yapan, dosyalarin gecerli
    bir donme kaydiyla baslamasidir (bkz. dogrula). Kac dosyanin gitmis
    olmasi GEREKTIGINI ise dosya bilemez; tanik bilir (karsilastir).
    """
    dosyalar = list(dosyalar)

    def akis():
        for d in dosyalar:
            with open(d, encoding="utf-8", errors="replace") as f:
                for i, satir in enumerate(f, 1):
                    yield f"{Path(d).name}:{i}", satir
    return dogrula(akis(), rotasyon_olabilir=len(dosyalar) > 1)


# ── Iki tanigi karsilastirma ─────────────────────────────────────────────────
#
# Saf fonksiyonlar: veritabanini bilmezler. Tanigin halkalari onlara
# liste olarak verilir -- (sira, ozet, govde, zaman).

@dataclass
class Karsilastirma:
    dosya_halka: int = 0
    tanik_halka: int = 0
    eslesen: int = 0
    dosyada_yok: list = field(default_factory=list)   # [(sira, govde)] tanikta var, dosyada yok
    farkli: list = field(default_factory=list)        # [sira] ikisinde de var, icerik ya da ozet farkli
    taniksiz: list = field(default_factory=list)      # [sira] dosyada var, tanikta yok
    tanik_oncesi: int = 0      # dosyada; tanigin dogumundan once yazilmis
    dosya_oncesi: int = 0      # tanikta; dosyalarin okunabilen basindan once (rotasyon)
    rotasyon_tanikla: bool = False  # dosya_oncesi tanigin donme kayitlariyla dogrulandi mi
    sifirlanmis: bool = False  # tanigin olmasi gereken halkalari bastan eksik: silinmis
    onay_kapsami: int | None = None
    onaylanan: list = field(default_factory=list)    # [(tur, sira)] -- gorulup onaylanmis
    kimlikler: dict = field(default_factory=dict)    # (tur, sira) -> bulgu kimligi

    @property
    def uyusuyor(self) -> bool:
        return not (self.dosyada_yok or self.farkli or self.taniksiz)


def karsilastir(dosya_halkalari, tanik_halkalari, onaylar=None,
                tanik_baslangici=None, bas_rotasyon=True,
                yedek_sayisi=None) -> Karsilastirma:
    """Dosyadaki zinciri tanigin kopyasiyla halka halka yan yana koyar.

    dosya_halkalari: Rapor.halkalar -- (sira, ozet, konum, govde)
    tanik_halkalari: (sira, ozet, govde, zaman)
    onaylar:          Rapor.onaylar -- yalnizca LISTELENEN farklar onayli
    tanik_baslangici: Rapor.tanik_baslangici -- tanik bu halkadan beri
                      tutuyor; ondan sonraki her halka tanikta olmali
    bas_rotasyon:     Rapor.bas_rotasyon -- dosyanin basindaki eksiklik
                      rotasyon olabilir mi; olamazsa tanikta kalanlar
                      'dosyada yok' sayilir
    yedek_sayisi:     RotatingFileHandler backupCount. Verilirse rotasyonla
                      gitmis olmasi BEKLENEN halkalar tanigin kendi donme
                      kayitlarindan hesaplanir: en son kayit ana dosyayi,
                      ondan oncekiler donmus dosyalari baslatir ve
                      yedek_sayisi kadar donmus dosya tutulur. Daha
                      eskisinin gitmis olmasi beklenir; gerisi silmedir.
                      Dosya bunu bilemez -- butun bir eski dosyanin
                      silinmesini ancak tanik gorur (en eski yedeginkini
                      bir sonraki rotasyona kadar; bkz. ROTASYON).

    Ozet kadar ICERIK de karsilastirilir: ozetine dokunulmadan
    degistirilen bir satiri dosyanin kendi dogrulayicisi zaten yakalar;
    burada da yakalanmasi, ikisinden birindeki bir hatanin otekini
    sessize almamasi icin. iki_tanigi_karsilastir() bu parametreleri
    rapordan kendisi doldurur; elle cagiran unutmasin diye.
    """
    k = Karsilastirma()
    d = {}
    for sira, oz, _konum, govde in dosya_halkalari:
        d.setdefault(sira, (oz, govde))     # tekrar eden sira: dosya dogrulayicisinin isi
    t = {}
    for sira, oz, govde, _zaman in tanik_halkalari:
        t[sira] = (oz, govde)
    k.dosya_halka, k.tanik_halka = len(d), len(t)
    d_ilk = min(d) if d else None
    t_ilk = min(t) if t else None

    beklenen_ilk = None             # rotasyondan sonra dosyalarda kalmasi gereken ilk halka
    if yedek_sayisi is not None:
        k.rotasyon_tanikla = True
        donmeler = sorted(s for s, (_oz, govde) in t.items() if _ROTASYON.search(govde))
        if len(donmeler) > yedek_sayisi:
            beklenen_ilk = donmeler[-(yedek_sayisi + 1)]

    def rotasyonla_gitti(sira):
        if not bas_rotasyon or d_ilk is None or sira >= d_ilk:
            return False
        return yedek_sayisi is None or (beklenen_ilk is not None and sira < beklenen_ilk)

    for sira in sorted(t):
        if sira in d:
            if d[sira] == t[sira]:
                k.eslesen += 1
            else:
                k.farkli.append(sira)
                k.kimlikler[("farklı", sira)] = bulgu_kimligi("farkli", sira, *d[sira], *t[sira])
        elif rotasyonla_gitti(sira):
            k.dosya_oncesi += 1
        else:
            k.dosyada_yok.append((sira, t[sira][1]))
            k.kimlikler[("dosyada yok", sira)] = bulgu_kimligi("dosyada_yok", sira, *t[sira])
    # Tanigin dogum kaydi varsa sinir ODUR, tanigin bugunku ilk halkasi
    # degil: silinip yeniden kurulan bir tanik gec baslar.
    sinir = tanik_baslangici if tanik_baslangici is not None else t_ilk
    for sira in sorted(d):
        if sira in t:
            continue
        if sinir is None or sira < sinir:
            k.tanik_oncesi += 1
        else:
            k.taniksiz.append(sira)
            k.kimlikler[("tanıksız", sira)] = bulgu_kimligi("taniksiz", sira, *d[sira])

    # Onay: istendigi anda gorulmus ve LISTELENMIS farklar gecmise tasinir.
    if onaylar:
        k.onay_kapsami = max(kapsam for _s, kapsam, _k, _l in onaylar)

        def onayli(tur, sira):
            kimlik = k.kimlikler[(tur, sira)]
            return any(kimlik in liste and sira <= kapsam for _s, kapsam, _k, liste in onaylar)

        k.onaylanan = (
            [("dosyada yok", s) for s, _ in k.dosyada_yok if onayli("dosyada yok", s)]
            + [("farklı", s) for s in k.farkli if onayli("farklı", s)]
            + [("tanıksız", s) for s in k.taniksiz if onayli("tanıksız", s)]
        )
        k.dosyada_yok = [(s, g) for s, g in k.dosyada_yok if not onayli("dosyada yok", s)]
        k.farkli = [s for s in k.farkli if not onayli("farklı", s)]
        k.taniksiz = [s for s in k.taniksiz if not onayli("tanıksız", s)]
    # Tanik, dogumundan sonraki halkalari bastan kaybetmis mi (silinip
    # yeniden kurulmus ya da basi kesilmis)? Onaylanmamis kayip varsa.
    k.sifirlanmis = tanik_baslangici is not None and any(
        t_ilk is None or s < t_ilk for s in k.taniksiz)
    return k


def tanik_raporu(tanik_halkalari) -> Rapor:
    """Tanigin KENDI zinciri: kopyanin icinde oynanmis mi?

    Tanik dogdugu halkadan baslar: basinin eksik olmasi olagan. Basindan
    halka silinmesini dogum kaydi yakalar (yazici ve karsilastir)."""
    return dogrula(
        ((f"tanık:{sira}", f"{govde} | ozet={oz}")
         for sira, oz, govde, _zaman in sorted(tanik_halkalari, key=lambda h: h[0])),
        bas_serbest=True,
    )


def iki_tanigi_karsilastir(dosya_r: Rapor, tanik_halkalari, yedek_sayisi=None):
    """(Karsilastirma, tanigin kendi raporu) -- dosya raporundaki her seyle."""
    tanik_halkalari = list(tanik_halkalari)
    k = karsilastir(dosya_r.halkalar, tanik_halkalari, onaylar=dosya_r.onaylar,
                    tanik_baslangici=dosya_r.tanik_baslangici,
                    bas_rotasyon=dosya_r.bas_rotasyon, yedek_sayisi=yedek_sayisi)
    return k, tanik_raporu(tanik_halkalari)


def acik_bulgular(dosya_r: Rapor, k: Karsilastirma | None = None,
                  tanik_r: Rapor | None = None) -> tuple[list, list]:
    """Henuz onaylanmamis bulgular: (okunur satirlar, kimlikler).

    /iz_onayla bunu gosterir ve onay satirina YALNIZCA bu kimlikleri
    yazar. Onaydan sonra dogan bir bulgu bu listede olmadigi icin
    onayli sayilmaz -- eski bir satira dokunulmus olsa bile.
    """
    satirlar, kimlikler = [], []
    for x in dosya_r.sorunlar:
        yer = f"sıra {x.sira} · " if x.sira else f"{x.konum} · "
        satirlar.append(f"❌ {yer}{x.aciklama}")
        kimlikler.append(x.kimlik)
    for x in dosya_r.mudahaleler:
        satirlar.append(f"⚠️ sıra {x.sira} · {x.aciklama}")
        kimlikler.append(x.kimlik)
    if k is not None:
        if k.dosyada_yok:
            satirlar.append(f"❌ tanıkta var, dosyada yok: {aralik([s for s, _ in k.dosyada_yok])}")
            kimlikler += [k.kimlikler[("dosyada yok", s)] for s, _ in k.dosyada_yok]
        if k.farkli:
            satirlar.append(f"❌ iki tanıkta farklı: {aralik(k.farkli)}")
            kimlikler += [k.kimlikler[("farklı", s)] for s in k.farkli]
        if k.taniksiz:
            ne = "tanık sıfırlanmış, tanıkta yok" if k.sifirlanmis else "tanıksız"
            satirlar.append(f"⚠️ {ne}: {aralik(k.taniksiz)}")
            kimlikler += [k.kimlikler[("tanıksız", s)] for s in k.taniksiz]
    if tanik_r is not None and tanik_r.sorunlar:
        satirlar.append(f"❌ tanığın kendi zinciri: {tanik_r.sorunlar[0].aciklama}")
        kimlikler += [x.kimlik for x in tanik_r.sorunlar]
    return satirlar, kimlikler


ONAY_EN_FAZLA = 200     # tek onay satirinda en fazla bu kadar bulgu


def onay_ayrintisi(kapsam: int, kimlikler) -> str:
    """Onay satirinin ayrintisi: 'kapsam=N bulgu=M onay=k1,k2,...'."""
    kimlikler = list(dict.fromkeys(kimlikler))[:ONAY_EN_FAZLA]
    return f"kapsam={kapsam} bulgu={len(kimlikler)} onay={','.join(kimlikler)}"


def aralik(siralar) -> str:
    """[3, 4, 5, 9] -> 'sıra 3–5, 9'"""
    parcalar, bas, son = [], None, None
    for s in sorted(siralar):
        if bas is not None and s == son + 1:
            son = s
            continue
        if bas is not None:
            parcalar.append(f"{bas}" if bas == son else f"{bas}–{son}")
        bas = son = s
    if bas is not None:
        parcalar.append(f"{bas}" if bas == son else f"{bas}–{son}")
    return "sıra " + ", ".join(parcalar)


_OLAY = re.compile(r"AUDIT \| ([^|]+?) \|")


def _olay_ozeti(govde: str) -> str:
    """'03.10 22:16:51 · sovereign_audit' -- tanikta kalan satirdan."""
    damga = govde[:19]
    try:
        yil, ay, gun = damga[:10].split("-")
        zaman = f"{gun}.{ay} {damga[11:19]}"
    except ValueError:
        zaman = "?"
    m = _OLAY.search(govde)
    return f"{zaman} · {m.group(1) if m else '?'}"


def tanik_ozet_satiri(k: Karsilastirma, tanik_r: Rapor) -> str:
    """Tek satir: saglik raporu icin."""
    if k.tanik_halka == 0 and k.uyusuyor:
        return "tanık henüz boş"
    parcalar = []
    if k.dosyada_yok:
        parcalar.append(f"{len(k.dosyada_yok)} halka dosyada yok "
                        f"({aralik([s for s, _ in k.dosyada_yok])})")
    if k.farkli:
        parcalar.append(f"{len(k.farkli)} halka farklı ({aralik(k.farkli)})")
    if k.taniksiz and not k.sifirlanmis:
        parcalar.append(f"{len(k.taniksiz)} halka tanıksız ({aralik(k.taniksiz)})")
    if not tanik_r.saglam:
        parcalar.append("tanığın kendi zinciri kırık")
    onayli = f" · onaylı: {len(k.onaylanan)} halka" if k.onaylanan else ""
    if k.sifirlanmis:
        # "tanık: tanık sıfırlanmış" demesin: en agir bulgu satiri baslatir.
        bas = f"tanık sıfırlanmış: {len(k.taniksiz)} halka tanıkta yok ({aralik(k.taniksiz)})"
        return ", ".join([bas] + parcalar) + onayli
    if not parcalar:
        return f"tanık uyuşuyor ({k.eslesen} halka){onayli}"
    return "tanık: " + ", ".join(parcalar) + onayli


def karsilastirma_metni(k: Karsilastirma, dosya_r: Rapor, tanik_r: Rapor,
                        en_fazla: int = 10) -> str:
    s = ["🔗 Denetim izi — iki tanık"]
    s.append(f"   Dosya: {ozet_satiri(dosya_r)}")
    tanik_durum = ("zincir sağlam" if tanik_r.saglam
                   else ozet_satiri(tanik_r).split(" · ")[0])
    s.append(f"   Tanık (veritabanı): {k.tanik_halka} halka · {tanik_durum}")

    if k.dosyada_yok:
        s.append(f"❌ {len(k.dosyada_yok)} halka tanıkta var, dosyada yok:")
        for sira, govde in k.dosyada_yok[:en_fazla]:
            s.append(f"   sıra {sira} · {_olay_ozeti(govde)}")
        if len(k.dosyada_yok) > en_fazla:
            s.append(f"   … ve {len(k.dosyada_yok) - en_fazla} halka daha")
    if k.farkli:
        s.append(f"❌ {len(k.farkli)} halka iki tanıkta farklı: {aralik(k.farkli)}")
        s.append("   (dosya ya da veritabanı, yazıldıktan sonra değiştirilmiş)")
    if k.sifirlanmis:
        s.append(f"❌ Tanık sıfırlanmış: {len(k.taniksiz)} halka dosyada var, tanıkta yok: "
                 f"{aralik(k.taniksiz)}")
        s.append("   (dosyaya göre tanık bu halkaları tutuyordu; tablo silinmiş ya da başı kesilmiş)")
    elif k.taniksiz:
        s.append(f"⚠️ {len(k.taniksiz)} halka dosyada var, tanıkta yok: {aralik(k.taniksiz)}")
        s.append("   (veritabanı o sırada yazılamamış, tanıktan silinmiş ya da satır "
                 "bot dururken dosyaya eklenmiş olabilir)")
    if not tanik_r.saglam:
        ilk = tanik_r.sorunlar[0]
        s.append(f"❌ Tanığın kendi zinciri kırık: {ilk.konum} — {ilk.aciklama}")
    if k.tanik_oncesi:
        s.append(f"   {k.tanik_oncesi} halka tanıktan önce yazılmış (tanık doğrulayamaz)")
    if k.dosya_oncesi and k.rotasyon_tanikla:
        s.append(f"   {k.dosya_oncesi} halka yalnızca tanıkta: rotasyonla silinmiş "
                 f"(tanıktaki dönme kayıtlarıyla uyumlu)")
    elif k.dosya_oncesi:
        s.append(f"   {k.dosya_oncesi} halka yalnızca tanıkta: dosyaların başından önce "
                 f"(rotasyonla silinmiş olabilir)")
    if k.onaylanan:
        turler = {}
        for tur, sira in k.onaylanan:
            turler.setdefault(tur, []).append(sira)
        ozet = "; ".join(f"{tur}: {aralik(siralar)}" for tur, siralar in turler.items())
        s.append(f"✔ Onaylanmış geçmiş (kapsam sıra ≤ {k.onay_kapsami}): {ozet}")

    if dosya_r.eski_onaylar:
        s.append(_eski_onay_notu(dosya_r))
    if k.uyusuyor and tanik_r.saglam:
        if k.tanik_halka == 0:
            s.append("   Tanık henüz boş: bundan sonraki halkalar iki yerde birden tutulacak.")
        elif dosya_r.temiz:
            s.append(f"✅ İki tanık uyuşuyor: {k.eslesen} halka.")
        else:
            s.append(f"⚠️ İki tanık uyuşuyor ({k.eslesen} halka); ama dosyanın kendi "
                     f"doğrulaması temiz değil: {ozet_satiri(dosya_r)}.")
    return "\n".join(s)


def ozet_satiri(r: Rapor) -> str:
    """Tek satirlik durum: saglik raporu icin."""
    if r.halka == 0 and r.saglam:
        return "zincir henüz boş"
    if r.saglam:
        s = f"zincir sağlam ({r.halka} halka)"
    else:
        ilk = r.sorunlar[0]
        ek = f" (+{len(r.sorunlar) - 1} sorun)" if len(r.sorunlar) > 1 else ""
        yer = f"sıra {ilk.sira}" if ilk.sira else ilk.konum
        s = f"zincir kırık: {yer}{ek}"
    if r.mudahaleler:
        ilk = r.mudahaleler[0]
        ek = f" (+{len(r.mudahaleler) - 1})" if len(r.mudahaleler) > 1 else ""
        s += f" · dış müdahale kaydı: sıra {ilk.sira}{ek}"
    if r.onaylanan:
        s += f" · onaylı geçmiş: {len(r.onaylanan)} bulgu"
    return s


def _eski_onay_notu(r: Rapor) -> str:
    """Eski bicim onay: yerine yenisi geldiyse bilgi, gelmediyse uyari."""
    yerler = ", ".join(f"sıra {sira}" for sira, _ in r.eski_onaylar)
    son_eski = max(sira for sira, _ in r.eski_onaylar)
    yeniler = [sira for sira, *_ in r.onaylar if sira > son_eski]
    if yeniler:
        return (f"ℹ️ Eski biçimli onay ({yerler}) yok sayıldı; yerini yeni biçimli onay "
                f"aldı (sıra {max(yeniler)}).")
    return (f"⚠️ Eski biçimli onay ({yerler}) artık geçerli değil: bulguları adıyla "
            f"listelemiyor, bir aralığı onaylıyordu. /iz_onayla ile yeniden onaylayın.")


def rapor_metni(r: Rapor, ad: str = "") -> str:
    s = [f"🔗 Denetim izi zinciri{(' — ' + ad) if ad else ''}"]
    if r.zincir_oncesi and r.halka:
        s.append(f"   {r.zincir_oncesi} satır zincirden önce yazılmış (doğrulanamaz)")
    if r.baslangic_eksik:
        a, b = r.baslangic_eksik
        aralik = f"sıra {a}" if a == b else f"sıra {a}–{b}"
        if r.mudahaleler and r.mudahaleler[0].sira == b + 1:
            # Ilk halka yazicinin kendi bildirimi: rotasyon degil, silme.
            s.append(f"   başlangıç eksik: {aralik} — yazıcı tam bu noktada "
                     f"dış müdahale kaydetmiş (aşağıda)")
        elif r.bas_rotasyon:
            s.append(f"   başlangıç eksik: {aralik} rotasyonla silinmiş: dosyalar bir dönme "
                     f"kaydıyla başlıyor (bütün bir eski dosyanın silinmediğini dosya tek "
                     f"başına kanıtlayamaz; tanık kanıtlar)")
        else:
            s.append(f"   başlangıç eksik: {aralik} — rotasyon değil, silme (aşağıda)")
    if r.halka:
        s.append(f"   {r.halka} halka okundu · son sıra {r.son_sira} · uç {r.son_ozet[:12]}…")
    if r.sorunlar:
        s.append(f"❌ Zincir kırık — {len(r.sorunlar)} sorun:")
        for x in r.sorunlar:
            sira = f"sıra {x.sira} · " if x.sira else ""
            s.append(f"   {sira}{x.konum} — {x.aciklama}")
    if r.mudahaleler:
        s.append(f"⚠️ Yazıcı {len(r.mudahaleler)} dış müdahale kaydetmiş:")
        for x in r.mudahaleler:
            s.append(f"   sıra {x.sira} · {x.konum} — {x.aciklama}")
    if r.onaylanan:
        o_sira, kapsam, o_konum = r.onay
        kac = f"; {len(r.onaylar)} onay" if len(r.onaylar) > 1 else ""
        s.append(f"✔ Onaylanmış geçmiş — {len(r.onaylanan)} bulgu "
                 f"(kapsam sıra ≤ {kapsam}; onay: sıra {o_sira} · {o_konum}{kac}):")
        for x in r.onaylanan:
            sira = f"sıra {x.sira} · " if x.sira else ""
            s.append(f"   {sira}{x.konum} — {x.aciklama}")
        s.append("   Not: onay da dosyadaki bir satır; sahte olup olmadığını dosya tek "
                 "başına söyleyemez, tanık söyler (/iz_dogrula).")
    if r.eski_onaylar:
        s.append(_eski_onay_notu(r))
    if r.halka == 0 and r.saglam:
        # Hicbir sey dogrulanmadi: bunu "sorun yok" gibi gostermek yesil yalan.
        if r.zincir_oncesi:
            s.append(f"⚠️ Zincirli satır yok: {r.zincir_oncesi} denetim satırının hiçbiri doğrulanamaz.")
            s.append("   Bu dosyaya yazan bot zincirli yazıcıyla mı çalışıyor? "
                     "Zincirli satırlar \"| sira=… | ozet=…\" ile biter.")
        else:
            s.append("⚠️ Dosyada denetim satırı yok: doğrulanacak bir şey yok.")
    elif r.temiz:
        s.append("✅ Zincir sağlam.")
    elif r.saglam:
        s.append("⚠️ Zincir kendi içinde tutarlı; ama dosyaya dışarıdan dokunulmuş.")
    return "\n".join(s)


def main(argv=None) -> int:
    """Cikis kodu -- betiklerde '&& echo tamam' guvenle kullanilabilsin diye:

    0  en az bir halka dogrulandi; zincir saglam, dis mudahale yok
       (onaylanmis bulgular haric: 0, onaylarin GERCEK oldugunu kanitlamaz --
       onay da dosyadaki bir satir; sahtesini yalnizca tanik ayirt eder)
    1  zincir kirik ya da yazici dis mudahale kaydetmis
    2  kullanim hatasi ya da dosya yok
    3  dogrulanacak halka yok -- hicbir sey dogrulanmadi, 'tamam' da denemez
    """
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("Kullanım: python3 audit_chain.py denetim/denetim.log")
        return 2
    dosyalar = dosyalari_sirala(args[0])
    if not dosyalar:
        print(f"Dosya bulunamadı: {args[0]}")
        return 2
    r = dogrula_dosyalar(dosyalar)
    print(rapor_metni(r, Path(args[0]).name))
    if not r.temiz:
        return 1
    return 0 if r.halka else 3


if __name__ == "__main__":
    sys.exit(main())
