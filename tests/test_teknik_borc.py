"""Teknik borc kapatma: log rotasyonu, audit ayrimi, ayarlanabilir
limitler ve tek onay mekanizmasi.

Bunlarin hicbiri yeni bir ozellik degil. Hepsi, sistem buyudukce
rahatsiz eden kucuk tutarsizliklar. Test edilmelerinin sebebi de bu:
geri gelmesinler.
"""
import inspect
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest


# ── 1. Log rotasyonu ─────────────────────────────────────────────────────────

def test_log_dosyasi_doner(vasi_module):
    """Sinirsiz buyuyen bir log dosyasi diski doldurur.

    NOT: pytest kok logger'i kendi yapilandirdigi icin calisma aninda
    kontrol edilemiyor; bunun yerine kaynak kodda dogruluyoruz.
    """
    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    assert "RotatingFileHandler(" in kaynak
    assert "handlers=[_doner_dosya(LOG_FILE)" in kaynak


def test_log_sinirlari_ayarlanabilir(vasi_module):
    v = vasi_module
    assert v.LOG_MAX_BYTES > 0
    assert v.LOG_BACKUP_COUNT > 0
    kaynak = (Path(v.__file__)).read_text(encoding="utf-8")
    assert 'os.getenv("LOG_MAX_BYTES"' in kaynak
    assert 'os.getenv("LOG_BACKUP_COUNT"' in kaynak


def test_basicconfig_duz_filehandler_kullanmiyor(vasi_module):
    """Eski `logging.FileHandler(LOG_FILE)` geri gelmemeli."""
    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    assert "logging.FileHandler(LOG_FILE)" not in kaynak


# ── 2. Audit ayrimi ──────────────────────────────────────────────────────────

def test_audit_ayri_dosyaya_yaziliyor(vasi_module):
    """Denetim kayitlari gurultuden ayrilmali.

    Bu testin onceki hali kaynak kodda bir satiri HARFI HARFINE
    ariyordu ('_audit_yazici = _doner_dosya(AUDIT_LOG_FILE)'). Faz 3'te
    o satirin yazilisi degisti, davranis degismedi -- ve test kirmizi
    oldu. Metni olcen test, kodun ne yaptigini degil nasil yazildigini
    olcer. Simdi gercekten yaziyor ve dosyaya bakiyor.
    """
    v = vasi_module
    v.audit_event("ayrim_sinamasi", "123456", "x")
    v.logger.info("siradan bir log satiri")

    denetim = Path(v.AUDIT_LOG_FILE).read_text(encoding="utf-8")
    assert "AUDIT | ayrim_sinamasi" in denetim
    assert "siradan bir log satiri" not in denetim, (
        "Genel log satiri denetim izine sizdi"
    )


def test_audit_filtresi_sadece_audit_geciriyor(vasi_module):
    """Genel loglar audit dosyasini kirletmemeli."""
    v = vasi_module
    filtre = v._SadeceAudit()

    audit_kaydi = logging.LogRecord(
        "vasi", logging.INFO, "", 0, "AUDIT | test | user=1 | detay", None, None
    )
    normal_kayit = logging.LogRecord(
        "vasi", logging.INFO, "", 0, "✅ Yanıt hazırlandı", None, None
    )
    assert filtre.filter(audit_kaydi) is True
    assert filtre.filter(normal_kayit) is False


def test_audit_genel_logdan_silinmiyor(vasi_module):
    """Olay sirasi genel logda korunmali; audit dosyasi EK bir kopya."""
    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    # audit_event hala normal logger.info kullaniyor olmali
    audit_kaynak = inspect.getsource(vasi_module.audit_event)
    assert "logger.info(" in audit_kaynak


# ── 3. Ayarlanabilir limitler ────────────────────────────────────────────────

@pytest.mark.parametrize("ad", [
    "RATE_LIMIT_WINDOW",
    "RATE_LIMIT_REQUESTS",
    "GEMINI_RATE_LIMIT_REQUESTS",
    "GEMINI_DAILY_LIMIT_REQUESTS",
])
def test_limitler_env_uzerinden_okunuyor(vasi_module, ad):
    """Sabit kodlanmis bir limit, dagitim basina ayarlanamaz."""
    kaynak = (Path(vasi_module.access.__file__)).read_text(encoding="utf-8")
    assert f'os.getenv("{ad}"' in kaynak, f"{ad} .env'den okunmuyor"


def test_limitler_sayi_olarak_geliyor(vasi_module):
    """getenv metin dondurur; int() cevrimi unutulmamali."""
    a = vasi_module.access
    for ad in ("RATE_LIMIT_WINDOW", "RATE_LIMIT_REQUESTS",
               "GEMINI_RATE_LIMIT_REQUESTS", "GEMINI_DAILY_LIMIT_REQUESTS"):
        assert isinstance(getattr(a, ad), int), f"{ad} int degil"


# ── 4. Tek onay mekanizmasi ──────────────────────────────────────────────────

def test_pending_save_tamamen_kaldirildi(vasi_module):
    """Iki ayri onay deseni, iki ayri hata yuzeyi demekti.

    /rapor kendi `pending_save` desenini, kendi callback formatini
    ve kendi butonlarini kullaniyordu. Bir onay mekanizmasina
    eklenen her guvenlik kontrolu (TTL, audit, yetki) digerine elle
    tasinmak zorundaydi.
    """
    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    assert "pending_save" not in kaynak
    assert "save_pending:" not in kaynak


def test_rapor_standart_mekanizmayi_kullaniyor(vasi_module):
    kaynak = inspect.getsource(vasi_module.cmd_rapor)
    assert "set_pending(" in kaynak
    assert '"save"' in kaynak


def test_tek_callback_formati(vasi_module):
    """Tum onay butonlari ayni callback desenini kullanmali."""
    kaynak = inspect.getsource(vasi_module.set_pending)
    assert 'callback_data="pending:yes"' in kaynak
    assert 'callback_data="pending:no"' in kaynak


def test_tum_onaylar_ttl_kontrolunden_geciyor(vasi_module):
    """Tek mekanizma = tek TTL kontrolu.

    Iki mekanizma varken TTL kontrolu iki ayri yerde yaziliydi;
    birine eklenen bir duzeltme digerine tasinmayabilirdi.
    """
    kaynak = inspect.getsource(vasi_module.callback_handler)
    assert kaynak.count("is_pending_expired(") == 1, (
        "birden fazla TTL kontrolu var; mekanizmalar tekrar ayrilmis olabilir"
    )


# ── Hata metni kaydedilmesin ─────────────────────────────────────────────────

@pytest.mark.parametrize("hatali", [
    "Model hatası: baglanti kurulamadi",
    "Model bulunamadı: yerel-genel",
    "❌ Rapor oluşturulamadı",
    "Hata: Güvensiz veya geçersiz URL.",
    "Radar Hatasi: Sayfa yüklenemedi.",
    "Güvenlik: Bu araç kullanımı yasaktır.",
    "",
    "   ",
])
def test_hata_metni_kaydedilebilir_sayilmiyor(vasi_module, hatali):
    """run_model_with_tools hata durumunda ISTISNA FIRLATMAZ.

    Hata metnini dondurur. Kontrol edilmezse o metin icerik sanilip
    dosyaya yazilir. Tam olarak bu yasandi: /rapor komutu bir
    baglanti hatasini notlar/ klasorune kaydetmek uzereydi.
    """
    assert vasi_module.model_ciktisi_kaydedilebilir(hatali) is False


@pytest.mark.parametrize("gecerli", [
    "# Rapor\n\nBu bir rapor icerigi.",
    "Turkuaz guzel bir renk.",
    "1. Madde\n2. Madde",
])
def test_gecerli_cikti_kaydedilebiliyor(vasi_module, gecerli):
    assert vasi_module.model_ciktisi_kaydedilebilir(gecerli) is True


def test_tum_uretim_noktalari_korunuyor(vasi_module):
    """Model ciktisini kaydetmeye sunan HER komut kontrol etmeli.

    Bir cagri noktasi atlanirsa, o komut hata metnini sessizce
    dosyaya yazar. LiteLLM fazinda benzer bir sey yasandi: dokuz
    komut model_for_role() yerine MODELS'i kullaniyordu.

    TARAMA FONKSIYON BASINA YAPILIR. Bunun bir onceki hali dosyayi
    bastan sona duz metin olarak tariyordu ve bekleyen bir model
    cagrisini fonksiyon sinirinin otesine tasiyabiliyordu: cmd_kod_patch
    (hic kaydetmeyen bir komut) ile cmd_hatirla (hic model cagirmayan
    bir komut) eslesiyor, araya sikismis olu bir koruma satiri da
    testi yesil tutuyordu. O satir NameError firlatiyordu ve /hatirla
    calismiyordu -- test bunu gormedi, cunku kaynak metnini kontrol
    ediyordu, davranisi degil.
    """
    import ast
    import re
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    satirlar = kaynak.split("\n")
    agac = ast.parse(kaynak)

    URETIM = re.compile(
        r"^(sonuc|arastirma) = "
        r"(await run_model_with_tools\(|gemini_grounded_research\()"
    )

    eksik = []
    kontrol_edilen = []
    for dugum in ast.walk(agac):
        if not isinstance(dugum, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        govde = satirlar[dugum.lineno - 1:dugum.end_lineno]   # yalniz bu fonksiyon
        bekleyen = None
        for i, satir in enumerate(govde):
            if URETIM.match(satir.strip()):
                bekleyen = i
            if bekleyen is not None and "preview, keyboard = set_pending(" in satir:
                arada = "\n".join(govde[bekleyen:i])
                mutlak = dugum.lineno + i
                kontrol_edilen.append(dugum.name)
                if "model_ciktisi_kaydedilebilir(" not in arada:
                    eksik.append(f"{dugum.name} (satir {mutlak})")
                bekleyen = None

    assert not eksik, f"Su set_pending cagrilari korumasiz: {eksik}"
    # Tarama kapsami daralirken sessizce hicbir seyi kontrol etmemeye
    # dusmesin: bes gercek cift korunuyor.
    assert len(kontrol_edilen) == 5, (
        f"Beklenen 5 uretim-kaydetme cifti, bulunan {len(kontrol_edilen)}: "
        f"{kontrol_edilen}"
    )


def test_basarisiz_uretim_kaydetme_sunmuyor(vasi_module):
    """Kullaniciya onay butonu YERINE hata mesaji gitmeli."""
    kaynak = inspect.getsource(vasi_module._uretim_basarisiz)
    assert "kaydetme iptal" in kaynak
    assert "set_pending" not in kaynak

# ── 5. /guvenlik raporunun iddialari koda uyuyor mu ──────────────────────────
#
# Rapor iki kisimdan olusuyor: kod sabitlerinden URETILEN satirlar ve
# ELLE YAZILAN "Sıradaki İyileştirmeler" listesi. Elle yazilan kisim
# kodla birlikte guncellenmezse rapor yanlis sey soyler -- ve bu rapor
# izleyiciye gosteriliyor.
#
# Gercek olay: liste "rotasyon yok; dosya sinirsiz buyuyor" diyordu.
# Kodda RotatingFileHandler vardi, 10 MB x 5 yedek. Iddia, anlattigi
# kodun tersini soyluyordu ve hicbir test bunu gormedi.
#
# Sapma denetcisinin kendi dersi: bir iddia, dogrulanabilir degilse
# iddia degildir.

def test_guvenlik_raporu_rotasyon_iddiasi_koda_uyuyor(vasi_module):
    """Kodda rotasyon varsa, rapor 'rotasyon yok' diyemez."""
    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    rapor = vasi_module.build_security_report()

    rotasyon_kodda = "RotatingFileHandler(" in kaynak
    assert rotasyon_kodda, "bu test rotasyonun var oldugunu varsayiyor"

    for yanlis in ("rotasyon yok", "sınırsız büyüyor", "sinirsiz buyuyor"):
        assert yanlis not in rapor, (
            f"Rapor '{yanlis}' diyor ama kodda RotatingFileHandler var. "
            f"Elle yazilan liste koddan sapmis."
        )


def test_guvenlik_raporu_rotasyon_sayilari_sabitlerden_geliyor(vasi_module):
    """Sayilar elle yazilirsa sabit degisince yalan olurlar."""
    v = vasi_module
    rapor = v.build_security_report()
    mb = v.LOG_MAX_BYTES // (1024 * 1024)
    assert f"{mb} MB × {v.LOG_BACKUP_COUNT} yedek" in rapor, (
        "Rotasyon sayilari rapora sabitlerden girmiyor"
    )


def test_guvenlik_raporu_maskeleme_iddiasi_koda_uyuyor(vasi_module):
    """Rapor maskeleme hakkinda ne diyorsa kod onu yapmali -- IKI YONDE.

    Bu testin ilk hali tek yonluydu ve kodun maskesiz yazdigini
    VARSAYIYORDU. Kod maskelemeye basladiginda sessizce yesil kalmadi:
    "bu test audit_event'in maskesiz yazdigini varsayiyor" diyerek
    dayandigi zeminin degistigini bildirdi. Iyi bir koruma testi
    boyle davranir -- ama tek yonlu bir koruma, yarim bir korumadir.

    Simdiki hali gercegi KAYNAK METNINDEN degil DAVRANISTAN turetiyor:
    audit_event()'i gercekten cagirir, yazilan satira bakar, sonra
    raporun ayni seyi soyleyip soylemedigini sinar. Kod hangi yone
    giderse gitsin, rapor pesinden gitmek zorunda.
    """
    import logging
    v = vasi_module

    class _Topla(logging.Handler):
        def __init__(self):
            super().__init__()
            self.satirlar = []

        def emit(self, kayit):
            self.satirlar.append(kayit.getMessage())

    topla = _Topla()
    lg = logging.getLogger("vasi")
    eski_seviye = lg.level
    lg.setLevel(logging.INFO)
    lg.addHandler(topla)
    try:
        v.audit_event("iddia_sinamasi", "987654321", "x")
    finally:
        lg.removeHandler(topla)
        lg.setLevel(eski_seviye)

    satir = next(s for s in topla.satirlar if "iddia_sinamasi" in s)
    kod_maskeliyor = "987654321" not in satir and "***321" in satir

    rapor = v.build_security_report()
    rapor_maskeli_diyor = "kimliği her yerde maskelenir" in rapor
    rapor_maskesiz_diyor = "log dosyasında değil" in rapor

    if kod_maskeliyor:
        assert rapor_maskeli_diyor and not rapor_maskesiz_diyor, (
            "Kod kimligi maskeliyor ama rapor bunu soylemiyor ya da "
            "tersini soyluyor."
        )
    else:
        assert rapor_maskesiz_diyor and not rapor_maskeli_diyor, (
            "Kod kimligi maskesiz yaziyor ama rapor maskeleme iddia ediyor."
        )

    # Ilk videodaki kosulsuz iddia bir daha geri gelmesin.
    assert "Hassas içerik maskeleyen `AUDIT` satırları tutulur." not in rapor


def test_guvenlik_raporu_duzelen_maddeleri_listelemiyor(vasi_module):
    """Duzeltilmis bir kusur 'siradaki iyilestirme' olarak kalmamali.

    Ters yondeki sapma: kod duzelir, liste guncellenmez, rapor artik
    var olmayan bir kusuru anlatir. Bu da yanlis bir rapordur.
    """
    rapor = vasi_module.build_security_report()
    liste = rapor[rapor.index("## Gerçekçi Sıradaki İyileştirmeler"):]
    for duzelen in (
        "iki kez yazılıyor",
        "kimliğini maskesiz yazıyor",
        "doğrudan birim testi yok",
        "ikinci tanığı yok",
    ):
        assert duzelen not in liste, (
            f"Duzeltilmis kusur hala listede: '{duzelen}'"
        )



# ── 6. Telegram metinlerinde Markdown isareti ────────────────────────────────

def test_telegram_metinlerinde_markdown_isareti_yok():
    """Bot hicbir yerde parse_mode kullanmiyor; '_metin_' ham gorunur.

    Sovereign'da parse_mode kaldirildi (alt cizgili kontrol adlari mesaji
    gonderilemez yapiyordu). Ama italik isaretleri metinlerde kaldi ve
    her ekran goruntusunde '_Kod, politika ve yapilandirma..._' diye,
    alt cizgileriyle gorundu.
    """
    import ast
    import re

    kok = Path(__file__).resolve().parents[1]
    italik = re.compile(r"(^|\s)_[^\s_][^_\n]*_(\s|$)")
    ihlaller = []
    for ad in ("vasi.py", "sovereign.py"):
        agac = ast.parse((kok / ad).read_text(encoding="utf-8"))
        for d in ast.walk(agac):
            if isinstance(d, ast.JoinedStr):
                metin = "".join(v.value if isinstance(v, ast.Constant) else "X"
                                for v in d.values)
            elif isinstance(d, ast.Constant) and isinstance(d.value, str):
                metin = d.value
            else:
                continue
            if italik.search(metin):
                ihlaller.append(f"{ad}:{d.lineno}  {metin.strip()[:60]!r}")
    assert not ihlaller, "Ham Markdown isareti:\n  " + "\n  ".join(ihlaller)
