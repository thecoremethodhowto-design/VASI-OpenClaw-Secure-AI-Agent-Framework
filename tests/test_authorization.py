"""is_authorized() icin testler.

Bu fonksiyon dort bagimsiz kontrol yapar:
  1. Kim      - MY_TELEGRAM_ID eslesmesi
  2. Nereden  - sadece ozel sohbet
  3. Nasil    - yonlendirilmis mesaj reddi
  4. Ne zaman - 60 saniyeden eski mesaj reddi (replay korumasi)

Her kontrol icin hem gecen hem reddedilen bir senaryo test edilir.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


AUTHORIZED_ID = 123456  # conftest.py icinde MY_TELEGRAM_ID olarak ayarli


def make_update(
    user_id: int = AUTHORIZED_ID,
    chat_type: str = "private",
    forwarded: bool = False,
    age_seconds: int = 0,
    with_message: bool = True,
):
    """Telegram Update nesnesinin test icin yeterli sahte karsiligi."""
    message = None
    if with_message:
        message = SimpleNamespace(
            date=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
            forward_origin=object() if forwarded else None,
        )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id, type=chat_type),
        message=message,
    )


# ── Temel durum ──────────────────────────────────────────────────────────────

def test_yetkili_kullanici_ozel_sohbette_kabul_edilir(vasi_module):
    assert vasi_module.is_authorized(make_update()) is True


# ── Kontrol 1: Kim ───────────────────────────────────────────────────────────

def test_farkli_kullanici_reddedilir(vasi_module):
    assert vasi_module.is_authorized(make_update(user_id=999999)) is False


def test_kimlik_kontrolu_diger_kontrollerden_once_calisir(vasi_module):
    """Yetkisiz kullanici, digerleri gecerli olsa bile reddedilmeli."""
    update = make_update(user_id=999999, chat_type="private", age_seconds=0)
    assert vasi_module.is_authorized(update) is False


# ── Kontrol 2: Nereden ───────────────────────────────────────────────────────

@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
def test_ozel_olmayan_sohbetler_reddedilir(vasi_module, chat_type):
    assert vasi_module.is_authorized(make_update(chat_type=chat_type)) is False


# ── Kontrol 3: Nasil ─────────────────────────────────────────────────────────

def test_yonlendirilmis_mesaj_reddedilir(vasi_module):
    assert vasi_module.is_authorized(make_update(forwarded=True)) is False


def test_yonlendirilmemis_mesaj_kabul_edilir(vasi_module):
    assert vasi_module.is_authorized(make_update(forwarded=False)) is True


# ── Kontrol 4: Ne zaman (replay korumasi) ────────────────────────────────────

def test_eski_mesaj_reddedilir(vasi_module):
    """60 saniyeden eski mesaj = olasi replay saldirisi."""
    assert vasi_module.is_authorized(make_update(age_seconds=120)) is False


def test_taze_mesaj_kabul_edilir(vasi_module):
    assert vasi_module.is_authorized(make_update(age_seconds=10)) is True


def test_sinir_altindaki_mesaj_kabul_edilir(vasi_module):
    """59 saniye: sinirin altinda, kabul edilmeli."""
    assert vasi_module.is_authorized(make_update(age_seconds=59)) is True


def test_sinir_ustundeki_mesaj_reddedilir(vasi_module):
    """61 saniye: sinirin ustunde, reddedilmeli."""
    assert vasi_module.is_authorized(make_update(age_seconds=61)) is False


# ── Kenar durumlar ───────────────────────────────────────────────────────────

def test_mesajsiz_update_kabul_edilir(vasi_module):
    """Callback query gibi mesajsiz guncellemeler mesaj kontrollerini atlar.

    Kimlik ve sohbet turu kontrolleri yine de calisir.
    """
    assert vasi_module.is_authorized(make_update(with_message=False)) is True


def test_mesajsiz_update_yetkisiz_kullanicida_reddedilir(vasi_module):
    update = make_update(user_id=999999, with_message=False)
    assert vasi_module.is_authorized(update) is False


def test_mesajsiz_update_grup_sohbetinde_reddedilir(vasi_module):
    update = make_update(chat_type="group", with_message=False)
    assert vasi_module.is_authorized(update) is False


def test_bos_telegram_id_kimlik_kontrolunu_devre_disi_birakir(vasi_module, monkeypatch):
    """MY_TELEGRAM_ID bos ise kimlik kontrolu atlanir.

    Bu bilinen ve belgelenmis bir davranistir (bkz. SECURITY.md ->
    Operator Sorumluluklari). Test, davranisin sessizce degismemesi
    icin vardir.
    """
    monkeypatch.setattr(vasi_module.access, "MY_TELEGRAM_ID", "")
    assert vasi_module.is_authorized(make_update(user_id=999999)) is True


def test_bos_telegram_id_diger_kontrolleri_etkilemez(vasi_module, monkeypatch):
    """Kimlik kontrolu devre disi olsa bile digerleri calismali."""
    monkeypatch.setattr(vasi_module.access, "MY_TELEGRAM_ID", "")
    assert vasi_module.is_authorized(make_update(chat_type="group")) is False
    assert vasi_module.is_authorized(make_update(forwarded=True)) is False
    assert vasi_module.is_authorized(make_update(age_seconds=120)) is False