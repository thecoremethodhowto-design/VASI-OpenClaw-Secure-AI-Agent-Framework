"""Denetim izi: audit_event() GERCEKTEN ne yaziyor.

Bu dosya neden var: depoda 'audit_event' gecen dort test vardi ve
dordu de kaynak METNINI kontrol ediyordu -- hicbiri fonksiyonu
cagirmiyordu. Sistemin butun guvenlik iddialari o izin dogru
yazdigina dayaniyor; o yuzden once izi gercekten uretip bakalim.

Asagidaki testlerin bir kismi SU ANKI KUSURLARI kilitliyor
(cift yazma, maskesiz kimlik). Bunlar bilerek boyle: once kusurun
var oldugunu kanitla, sonra duzelt, testin kirildigini gor. Bir
duzeltmenin gercekten bir sey degistirdigini ancak o zaman
bilirsin.
"""
import importlib
import inspect
import logging
import sys
from pathlib import Path

import pytest


# ── Yardimci: vasi'yi izole log dosyalariyla yukle ───────────────────────────

def _vasi_yukle(tmp_path, monkeypatch, genel_log, audit_log, yedek_log=None, kok_onceden=False):
    """vasi modulunu verilen log yollariyla bastan yukler.

    Logging kurulumu IMPORT ANINDA calisiyor, bu yuzden ortam
    degiskenlerini once ayarlayip modulu yeniden yuklemek sart.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("MY_TELEGRAM_ID", "123456")
    monkeypatch.setenv("WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("USE_LITELLM", "false")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VASI_LOG_FILE", str(genel_log))
    monkeypatch.setenv("AUDIT_LOG_FILE", str(audit_log))
    monkeypatch.setenv("AUDIT_YEDEK_LOG_FILE", str(yedek_log or tmp_path / "denetim_yedek.log"))
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)   # gercek veritabani yok

    kok = Path(__file__).resolve().parents[1]
    if str(kok) not in sys.path:
        sys.path.insert(0, str(kok))

    # Kok logger'in eski yazicilarini kapat: onceki testten kalan bir
    # dosya tutamagi, bu testin satirlarini baska dosyaya dusurur.
    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)
        h.close()
    vasi_logger = logging.getLogger("vasi")
    for h in list(vasi_logger.handlers):
        vasi_logger.removeHandler(h)
        h.close()

    for py in kok.glob("*.py"):
        sys.modules.pop(py.stem, None)

    if kok_onceden:
        # Bir kutuphane ya da test calistirici kok logger'a once dokunmus.
        logging.getLogger().addHandler(logging.NullHandler())
        logging.getLogger().setLevel(logging.WARNING)

    return importlib.import_module("vasi")


def _audit_satirlari(yol: Path):
    if not yol.exists():
        return []
    return [s for s in yol.read_text(encoding="utf-8").splitlines() if "AUDIT |" in s]


# ── 1. Fonksiyon gercekten calisiyor mu ──────────────────────────────────────

def test_audit_event_dosyaya_satir_yaziyor(tmp_path, monkeypatch):
    """En temel soru: cagirinca bir sey yaziliyor mu?

    Dort testin hicbiri bunu sormamisti.
    """
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    v = _vasi_yukle(tmp_path, monkeypatch, genel, audit)

    v.audit_event("test_olayi", "123456", "bir ayrinti")

    satirlar = _audit_satirlari(audit)
    assert satirlar, "audit dosyasina hicbir AUDIT satiri yazilmadi"
    assert "test_olayi" in satirlar[0]
    assert "bir ayrinti" in satirlar[0]


def test_audit_event_olay_adini_ve_ayrintiyi_ayri_tutuyor(tmp_path, monkeypatch):
    """Satir ayristirilabilir olmali -- zincir dogrulamasi buna bagli."""
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    v = _vasi_yukle(tmp_path, monkeypatch, genel, audit)

    v.audit_event("komut_calisti", "123456", "detay metni")

    satir = _audit_satirlari(audit)[0]
    govde = satir.split("AUDIT |", 1)[1]
    parcalar = [p.strip() for p in govde.split("|")]
    assert parcalar[0] == "komut_calisti"
    assert parcalar[1].startswith("user=")
    assert parcalar[2] == "detay metni"


def test_yeni_satir_enjeksiyonu_engelleniyor(tmp_path, monkeypatch):
    """Ayrintiya gomulen yeni satir AYRI bir AUDIT kaydi uretmemeli.

    sanitize_for_log() yeni satirlari bosluga ceviriyor; bu dogru
    calisiyor. Zincir eklendiginde kritik hale gelecek, o yuzden
    simdiden kilitliyoruz.
    """
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    v = _vasi_yukle(tmp_path, monkeypatch, genel, audit)

    v.audit_event("olay", "123456", "ilk satir\nAUDIT | sahte_olay | user=999 | uydurma")

    satirlar = _audit_satirlari(audit)
    assert len(satirlar) == 1, (
        f"Ayrintiya gomulen yeni satir ayri bir AUDIT kaydi uretti: {satirlar}"
    )


def test_boru_isareti_kaciriliyor(tmp_path, monkeypatch):
    """Ayrintidan gecen bir '|' satiri alanlarina bolemez.

    FAZ 2'de duzeltildi: sanitize_for_log() ayiriciyi degistiriyor.
    Satir her zaman tam olarak 3 alan tasir -- Faz 3'teki zincir
    dogrulamasi buna guveniyor.
    """
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    v = _vasi_yukle(tmp_path, monkeypatch, genel, audit)

    v.audit_event("olay", "123456", "zararsiz | gorunen | ayrinti")

    satir = _audit_satirlari(audit)[0]
    govde = satir.split("AUDIT |", 1)[1]
    alanlar = [p.strip() for p in govde.split("|")]

    # Faz 3'te zincir iki alan ekledi: sira ve ozet. Ayrinti yine TEK alan.
    assert len(alanlar) == 5, (
        f"Beklenen 5 alan (olay, user, ayrinti, sira, ozet), bulunan "
        f"{len(alanlar)}: {alanlar}. Ayrintiya gomulen bir ayirici satiri "
        f"bolebiliyor demektir."
    )
    assert alanlar[2] == "zararsiz ¦ gorunen ¦ ayrinti"
    assert alanlar[3].startswith("sira=") and alanlar[4].startswith("ozet=")


# ── 2. SU ANKI KUSURLAR: bunlar duzeltilince KIRILMALI ───────────────────────

def test_varsayilan_yollar_ayri(tmp_path, monkeypatch):
    """Iki ayri yazici, tek dosya.

    Kodun kendi yorumu soyle diyor:
        'Audit satirlari AYRICA kendi dosyasina yazilir.'
    Niyet iki dosya. Ama iki varsayilan da /tmp/vasi_audit.log idi.
    Niyet yorumda duruyor, davranista yok.

    FAZ 2'de varsayilanlar ayrilinca bu test KIRILACAK. Kirilmasi
    duzeltmenin kanitidir.
    """
    import os
    import re

    kaynak = (Path(__file__).resolve().parents[1] / "vasi.py").read_text(encoding="utf-8")

    genel_vars = re.search(r'VASI_LOG_FILE",\s*"([^"]+)"', kaynak).group(1)
    audit_vars = re.search(r'AUDIT_LOG_FILE",\s*"([^"]+)"', kaynak).group(1)

    assert genel_vars != audit_vars, (
        f"Iki yazici da '{genel_vars}' dosyasina bagli. Her AUDIT "
        f"satiri iki kez dusuyor ve rotasyon iki kat hizli doluyor."
    )


def test_ayni_yol_verilirse_tek_yazar(tmp_path, monkeypatch):
    """Iki yol ayni dosyayi gosterse bile satir BIR kez dusmeli.

    Faz 1'de bu test cift yazmayi kilitliyordu (2 satir). Faz 2'de
    kural mekanizmaya tasindi: yollar ayniysa ikinci yazici hic
    eklenmiyor. Varsayilani duzeltmek yetmezdi -- biri .env'de
    ikisini ayni yapabilir.
    """
    tek = tmp_path / "tek.log"
    v = _vasi_yukle(tmp_path, monkeypatch, tek, tek)

    v.audit_event("tekil_olay", "123456", "bir kez cagrildi")

    satirlar = [s for s in _audit_satirlari(tek) if "tekil_olay" in s]
    assert len(satirlar) == 1, (
        f"Tek cagri {len(satirlar)} satir uretti -- cift yazma geri geldi."
    )
    assert v.AUDIT_AYRI_DOSYADA is False


def test_modul_yeniden_yuklenince_yazici_birikmiyor(tmp_path, monkeypatch):
    """logging.getLogger("vasi") her seferinde AYNI nesneyi dondurur.

    Kurulum tekrar calistirilabilir degilken her yeniden yukleme bir
    yazici daha ekliyordu -- olculdu: bes yuklemede bes yazici. Test
    takimi modulu ~400 kez yukluyor; son testlerde her AUDIT satiri
    yuzlerce kez yaziliyor ve yuzlerce dosya tutamagi acik kaliyordu.
    """
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    _vasi_yukle(tmp_path, monkeypatch, genel, audit)

    kok = Path(__file__).resolve().parents[1]
    for _ in range(4):          # temizlemeden, testlerin yaptigi gibi
        for py in kok.glob("*.py"):
            sys.modules.pop(py.stem, None)
        importlib.import_module("vasi")

    denetim_yazicilari = [
        h for h in logging.getLogger("vasi").handlers
        if getattr(h, "_vasi_denetim_yazicisi", False)
    ]
    assert len(denetim_yazicilari) == 1, (
        f"Bes yuklemeden sonra {len(denetim_yazicilari)} denetim yazicisi var."
    )

def test_kimlik_dosyada_maskeli_yaziliyor(tmp_path, monkeypatch):
    """/audit_ozet kimligi '***456' diye maskeliyor; dosya yazmiyor.

    THREAT-MAPPING bir sure 'maskeleniyor' iddia etti -- yanlisti,
    duzelttik. Simdi kodu iddiaya uyduruyoruz.
    """
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    v = _vasi_yukle(tmp_path, monkeypatch, genel, audit)

    v.audit_event("olay", "987654321", "ayrinti")

    satir = _audit_satirlari(audit)[0]
    assert "user=***321" in satir, f"Kimlik maskesiz yazilmis: {satir}"
    assert "987654321" not in satir, f"Tam kimlik satirda duruyor: {satir}"


# ── 3. Observability yolu (maskeleme ORADA calisiyor) ────────────────────────

def test_observability_kaydinda_kimlik_maskeli(tmp_path, monkeypatch):
    """Ayni cagri iki yere gidiyor ve ikisi AYNI FIKIRDE DEGIL.

    Dosyaya acik, observability'ye maskeli. Tek bir audit_event()
    cagrisinin iki farkli gizlilik seviyesi uretmesi, kusurun
    kendisinden daha rahatsiz edici olani.
    """
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    v = _vasi_yukle(tmp_path, monkeypatch, genel, audit)

    v.audit_event("olay", "987654321", "ayrinti")

    kayitlar = [e for e in v.OBSERVABILITY.events
                if e.get("audit_event") == "olay"]
    assert kayitlar, "observability'ye kayit dusmedi"
    assert kayitlar[-1]["user_id"] == "***321"

    dosya_satiri = _audit_satirlari(audit)[0]
    assert "***321" in dosya_satiri
    assert "987654321" not in dosya_satiri


# ── 4. Kalicilik: iz yeniden baslatmadan sag cikiyor mu ──────────────────────
#
# Faz 3'un acilis bulgusu: denetim izi /tmp'deydi ve /tmp bir tmpfs'ti.
# Dosyanin ilk satiri hep botun son acilis ani; ondan oncesi yok.
# Veritabani 26 Eylul'u hatirlarken dosya bu aksami hatirlamiyordu.

BAGLAMALAR = """\
overlay / overlay rw,relatime 0 0
tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,relatime 0 0
/run/host_mark/Users /app/workspace fakeowner rw,nosuid,nodev,relatime 0 0
/run/host_mark/Users /app/denetim fakeowner rw,nosuid,nodev,relatime 0 0
"""


@pytest.mark.parametrize("yol, beklenen", [
    ("/tmp/vasi_audit.log",       "tmpfs"),      # Faz 2'ye kadarki hal
    ("/app/denetim/denetim.log",  "fakeowner"),  # kalici birim
    ("/app/vasi.py",              "overlay"),    # en uzun eslesme kazanir
    ("/tmpx/sahte.log",           "overlay"),    # '/tmp' onek tuzagi
])
def test_dosya_sistemi_olcumu(vasi_module, yol, beklenen):
    assert vasi_module.dosya_sistemi_turu(yol, BAGLAMALAR) == beklenen


def test_baglama_tablosu_yoksa_bilinmiyor(vasi_module):
    """Bilinmiyor, 'kalici' anlamina GELMEZ."""
    assert vasi_module.dosya_sistemi_turu("/app/denetim/x.log", "") is None


@pytest.mark.parametrize("tur, durum, sozcuk", [
    ("tmpfs",     "warn", "geçici bellekte"),
    ("fakeowner", "ok",   "kalıcı"),
    (None,        "warn", "doğrulanamadı"),
])
def test_saglik_satiri_olcume_dayaniyor(vasi_module, monkeypatch, tur, durum, sozcuk):
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: tur)
    satir = v.build_denetim_izi_health()
    assert satir.status == durum
    assert sozcuk in satir.details


def test_guvenlik_raporu_kaliciligi_dogru_soyluyor(vasi_module, monkeypatch):
    """Rapor 'kalici' derse olcum de kalici olmali -- iki yonde."""
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "tmpfs")
    rapor = v.build_security_report()
    assert "geçici bellekte" in rapor and "kalıcı ·" not in rapor

    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    rapor = v.build_security_report()
    assert "kalıcı ·" in rapor and "geçici bellekte" not in rapor


def test_saglik_raporunda_denetim_izi_satiri_var(vasi_module):
    assert "build_denetim_izi_health()" in inspect.getsource(
        vasi_module.build_health_report
    )


def test_yazilamayan_yolda_bot_cokmez_ve_soyler(tmp_path, monkeypatch):
    """Bozuk bir birim ayari botu durdurmamali; sessizce de gecmemeli.

    Engel bir DOSYA: onun altinda klasor acilamaz -- root icin bile.
    """
    engel = tmp_path / "engel"
    engel.write_text("ben bir dosyayim", encoding="utf-8")
    yedek = tmp_path / "yedek.log"

    v = _vasi_yukle(tmp_path, monkeypatch, tmp_path / "genel.log",
                    engel / "denetim.log", yedek_log=yedek)

    assert v.AUDIT_YEDEGE_DUSTU is True
    assert v.AUDIT_LOG_FILE == str(yedek)
    v.audit_event("yedek_sinamasi", "123456", "x")
    assert "yedek_sinamasi" in yedek.read_text(encoding="utf-8")

    satir = v.build_denetim_izi_health()
    assert satir.status == "warn"
    assert "istenen yola yazılamadı" in satir.details


def test_testler_gercek_ize_yazmiyor(vasi_module, tmp_path):
    """Testler botun ortamiyla calisiyor; gercek ize asla dokunmamali."""
    v = vasi_module
    assert Path(v.AUDIT_LOG_FILE).is_relative_to(tmp_path), v.AUDIT_LOG_FILE
    assert Path(v.LOG_FILE).is_relative_to(tmp_path), v.LOG_FILE
    assert not v.memory.is_configured(), "testler gercek veritabanina baglanabiliyor"


def test_kok_logger_onceden_yapilandirilmissa_iz_yine_yaziliyor(tmp_path, monkeypatch):
    """Denetim izi kok logger'in tesadufune bagli olmamali.

    basicConfig, kok logger'a once bir sey dokunduysa hata vermeden
    hicbir sey yapmaz. Bu duzeltilmeden once izde 0 satir oluyordu --
    sessizce. Testler alfabetik sirada baska bir yere dusunce bulundu.
    """
    genel, audit = tmp_path / "genel.log", tmp_path / "audit.log"
    v = _vasi_yukle(tmp_path, monkeypatch, genel, audit, kok_onceden=True)

    v.audit_event("kok_sinamasi", "123456", "x")

    assert any("kok_sinamasi" in s for s in _audit_satirlari(audit)), (
        "Kok logger onceden yapilandirilinca denetim izi yazilmadi"
    )
