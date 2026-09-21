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
    """Denetim kayitlari gurultuden ayrilmali."""
    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    assert "_audit_yazici = _doner_dosya(AUDIT_LOG_FILE)" in kaynak
    assert "_audit_yazici.addFilter(_SadeceAudit())" in kaynak
    assert "logger.addHandler(_audit_yazici)" in kaynak


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
    """
    import re
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    satirlar = kaynak.split("\n")

    eksik = []
    bekleyen = None
    for i, satir in enumerate(satirlar):
        sade = satir.strip()
        if re.match(r"^(sonuc|arastirma) = (await run_model_with_tools\(|gemini_grounded_research\()", sade):
            bekleyen = i
        if bekleyen is not None and "preview, keyboard = set_pending(" in satir:
            arada = "\n".join(satirlar[bekleyen:i])
            if "model_ciktisi_kaydedilebilir(" not in arada:
                eksik.append(f"satir {i + 1}")
            bekleyen = None

    assert not eksik, f"Su set_pending cagrilari korumasiz: {eksik}"


def test_basarisiz_uretim_kaydetme_sunmuyor(vasi_module):
    """Kullaniciya onay butonu YERINE hata mesaji gitmeli."""
    kaynak = inspect.getsource(vasi_module._uretim_basarisiz)
    assert "kaydetme iptal" in kaynak
    assert "set_pending" not in kaynak