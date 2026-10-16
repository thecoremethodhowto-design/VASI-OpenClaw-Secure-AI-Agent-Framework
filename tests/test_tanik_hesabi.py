"""Ikinci tanigin AYRI HESABI: bot tanigi silemez, kurali kapatamaz.

'Gunlukler Yalan Soyleyebilir mi?' (Ekim 2026) videosundaki dort denemenin
ikisi botun veritabani yetkisiyle yapildi: tanik tablosunu dusurmek ve
yalnizca-ekleme kuralini kapatip satir silmek. Bot super kullanici olarak
baglaniyordu ve super kullanicinin parolasi botun ortamindaydi (.env);
ayni parola veritabani kullanmayan LiteLLM'e de veriliyordu.

Bu dosya kurulumun SEKLINI ve botun yetki OLCUMUNU sinar. Veritabaninin
gercekten reddettigini gercek bir PostgreSQL'e karsi
tests/test_audit_store_pg.py sinar (VASI_TEST_PG).
"""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from test_ikinci_tanik import _SahteTanik

KOK = Path(__file__).resolve().parents[1]
KURULUM_SH = KOK / "scripts" / "postgres" / "kurulum.sh"


def _compose():
    return yaml.safe_load((KOK / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _ortam(servis) -> dict:
    ortam = servis.get("environment") or {}
    if isinstance(ortam, list):
        ortam = dict(x.split("=", 1) for x in ortam)
    return ortam


# ── 1. Sirlar: super kullanicinin parolasi yalnizca veritabaninda ───────────

def test_litellm_veritabani_sirri_almiyor():
    """LiteLLM veritabani kullanmiyor; parolasi ona verilmemeli."""
    ortam = _ortam(_compose()["litellm"])
    assert not [k for k in ortam if k.startswith("POSTGRES")], ortam
    assert "env_file" not in _compose()["litellm"]
    config = (KOK / "litellm" / "config.yaml").read_text(encoding="utf-8").lower()
    assert "database" not in config and "postgres" not in config, \
        "LiteLLM artik veritabani kullaniyorsa ona AYRI, kisitli bir hesap ver"


def test_veritabani_super_kullaniciyi_env_den_degil_kendi_dosyasindan_aliyor():
    """.env botun dosyasi (vasi-core onu tamamen alir). Super kullanicinin
    parolasi oraya yazilirsa botun icine girer."""
    pg = _compose()["postgres"]
    assert pg.get("env_file") in ("postgres.env", ["postgres.env"]), pg.get("env_file")
    ortam = _ortam(pg)
    for anahtar in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert anahtar not in ortam, f"postgres servisi {anahtar}'i .env'den aliyor"
    # Kurulum betigi botun parolasini .env'deki POSTGRES_PASSWORD'dan alir.
    assert ortam["VASI_BOT_PASSWORD"] == "${POSTGRES_PASSWORD:-}"
    assert ortam["VASI_BOT_USER"] == "${POSTGRES_USER:-vasi_bot}"
    assert "postgres.env" not in (_compose()["vasi-core"].get("env_file") or "")


def test_kurulum_betigi_veritabanina_bagli():
    birimler = _compose()["postgres"]["volumes"]
    assert "./scripts/postgres/kurulum.sh:/docker-entrypoint-initdb.d/10-vasi-tanik.sh:ro" in birimler
    assert "./scripts/postgres/tanik.sql:/vasi-kurulum/tanik.sql:ro" in birimler


def _ayarlar(dosya):
    """Yorum olmayan satirlar. Ornek dosyalar imaja kopyalanmaz: depo
    kopyasinda (YEREL=1 ./test.sh) calisir, konteynerde atlanir."""
    yol = KOK / dosya
    if not yol.exists():
        pytest.skip(f"{dosya} yok (konteynerde kopyalanmiyor)")
    return [x.strip() for x in yol.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.strip().startswith("#")]


def test_ornek_dosyalar_iki_hesabi_ayiriyor():
    assert "POSTGRES_USER=vasi_bot" in _ayarlar(".env.example")
    pg = _ayarlar("postgres.env.example")
    assert "POSTGRES_USER=vasi" in pg and "POSTGRES_USER=vasi_bot" not in pg


def test_postgres_env_git_e_ve_imaja_girmiyor():
    """commit_oncesi.sh da kontrol eder (takipte mi, yok sayiliyor mu, degerleri)."""
    for dosya in (".gitignore", ".dockerignore"):
        assert "postgres.env" in _ayarlar(dosya), dosya


# ── 2. Kurulum betiginin korkuluklari ──────────────────────────────────────

def _kurulum(**ortam):
    tam = {"PATH": os.environ.get("PATH", ""), "POSTGRES_USER": "vasi", "POSTGRES_DB": "vasi"}
    tam.update(ortam)
    return subprocess.run(["sh", str(KURULUM_SH)], env=tam, capture_output=True, text=True)


def test_kurulum_parolasizsa_atlaniyor_ilk_kurulumu_bozmuyor():
    """Bos parola = hafiza kapali. Ilk kurulumda betik basarisiz olsaydi
    resmi imaj yarim bir veritabani birakirdi; atlar ve soyler."""
    r = _kurulum(VASI_BOT_PASSWORD="")
    assert r.returncode == 0 and "ATLANDI" in r.stderr


def test_kurulum_botun_parolasi_super_kullanicininkiyle_ayniysa_durur():
    """Ayni parolayla bot super kullanici olarak da baglanabilirdi."""
    r = _kurulum(VASI_BOT_PASSWORD="ayni-parola-123", POSTGRES_PASSWORD="ayni-parola-123")
    assert r.returncode == 1 and "super kullanicininkiyle ayni" in r.stderr


def test_kurulum_botu_super_kullaniciyla_ayni_yapmiyor():
    """Eski .env'de POSTGRES_USER=vasi kalirsa bot yine super kullanici olurdu."""
    r = _kurulum(VASI_BOT_USER="vasi", VASI_BOT_PASSWORD="x")
    assert r.returncode == 1 and "super kullaniciyla ayni" in r.stderr


# ── 3. Bot yetkisini olcer ve soyler ───────────────────────────────────────

@pytest.fixture()
def yetkili_bot(vasi_module, monkeypatch):
    """Tanik bagli, PostgreSQL 'yapilandirilmis'; yetki olcumu taklit edilir."""
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    monkeypatch.setattr(v.memory, "is_configured", lambda: True)
    v._audit_yazici.tanik_bagla(_SahteTanik())
    durum = {"deger": (v.audit_store.YALNIZCA_EKLEME, "bot yalnızca ekleyebilir (vasi_bot)")}
    monkeypatch.setattr(v.audit_store, "yetki_durumu", lambda: durum["deger"])
    return v, durum


def test_saglik_yalnizca_ekleme_hesabinda_yesil(yetkili_bot):
    v, _ = yetkili_bot
    v.audit_event("bir", "123456", "x")
    saglik = v.build_denetim_izi_health()
    assert saglik.status == "ok", saglik.details
    assert "bot yalnızca ekleyebilir" in saglik.details


def test_saglik_bot_tanigi_silebiliyorsa_uyarir(yetkili_bot):
    """Kurulum betigi calismamis: bot hala super kullanici. Yesil yanmamali."""
    v, durum = yetkili_bot
    durum["deger"] = (v.audit_store.FAZLA_YETKI, "bot süper kullanıcı (vasi): tanığı silebilir")
    v.audit_event("bir", "123456", "x")
    saglik = v.build_denetim_izi_health()
    assert saglik.status == "warn" and "tanığı silebilir" in saglik.details


def test_denetci_fazla_yetkiyi_bulgu_sayiyor_ama_yetenek_kapatmiyor(yetkili_bot):
    v, durum = yetkili_bot
    durum["deger"] = (v.audit_store.FAZLA_YETKI, "bot tanığın sahibi (vasi_bot): tabloyu düşürebilir")
    v.audit_event("bir", "123456", "x")
    sonuc = v.sovereign.audit(v.guvenlik_anlik_goruntusu())
    bulgular = [(b.kontrol, b.onem) for b in sonuc.bulgular]
    assert ("iz_tanigi", "uyari") in bulgular, bulgular
    assert not sonuc.kapanacak_yetenekler, "iz bulgusu hicbir yetenegi kapatmamali"


def test_guvenlik_raporu_hesap_iddiasi_olcumden_geliyor(yetkili_bot):
    v, durum = yetkili_bot
    rapor = v.build_security_report()
    assert "botu ele geçiren tanığı silemez" in rapor
    durum["deger"] = (v.audit_store.FAZLA_YETKI, "bot süper kullanıcı (vasi): tanığı silebilir")
    rapor = v.build_security_report()
    assert "botu ele geçiren tanığı silemez" not in rapor
    assert "kurulum.sh` çalıştırılmalı" in rapor
