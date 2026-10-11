"""Duz bir mesaj UCTAN UCA: Telegram'dan gelir, cevap gider.

Bu dosya neden var: Faz 2'de log satirlarindaki kimligi maskelerken
message_handler icindeki satiri da degistirdim:

    user_id = update.effective_user.id          # Telegram: SAYI
    logger.info(f"... {mask_user_id(user_id)} ...")

mask_user_id() icinde len(user_id) cagriliyor; bir sayinin uzunlugu
olmaz -> TypeError. Satir try blogunun DISINDA oldugu icin kullaniciya
hata mesaji bile gitmedi: "merhaba" yazdin, bot sustu.

478 test yesildi. Cunku hicbir test duz bir mesaji gondermiyordu --
model cagirdigi icin. Yapisal kural testi satirin maskelendigini
kontrol ediyordu, argumanin turunu degil.

Buradaki testler modeli sahteliyor ama geri kalan her seyi GERCEKTEN
calistiriyor: yetki, hiz siniri, karar katmani, log satiri, cevap.
Kimlik gercek Telegram'daki gibi SAYI.
"""
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import asyncio
import pytest


class _Mesaj:
    def __init__(self, metin):
        self.text = metin
        self.date = datetime.now(timezone.utc)
        self.forward_origin = None
        self.gonderilen = []

    async def reply_text(self, metin, **kwargs):
        self.gonderilen.append(metin)


class _Bot:
    async def send_chat_action(self, **kwargs):
        return None


def _guncelleme(metin, kimlik=123456):
    return SimpleNamespace(
        message=_Mesaj(metin),
        effective_user=SimpleNamespace(id=kimlik),          # int, str DEGIL
        effective_chat=SimpleNamespace(id=kimlik, type="private"),
    )


class _Topla(logging.Handler):
    def __init__(self):
        super().__init__()
        self.satirlar = []

    def emit(self, kayit):
        self.satirlar.append(kayit.getMessage())


@pytest.fixture()
def sohbet(vasi_module, monkeypatch):
    """Modeli ve hafizayi sahteler; geri kalan her sey gercek."""
    v = vasi_module
    cagrilar = []

    async def sahte_model(model, metin, system_prompt, **kwargs):
        cagrilar.append(metin)
        return "selam, buradayim"

    monkeypatch.setattr(v, "run_model_with_tools", sahte_model)
    monkeypatch.setattr(v, "_aktif_hatiralar", lambda: [])

    topla = _Topla()
    lg = logging.getLogger("vasi")
    eski = lg.level
    lg.setLevel(logging.INFO)
    lg.addHandler(topla)
    yield v, cagrilar, topla
    lg.removeHandler(topla)
    lg.setLevel(eski)


def _gonder(v, metin):
    guncelleme = _guncelleme(metin)
    baglam = SimpleNamespace(bot=_Bot(), user_data={})
    asyncio.run(v.message_handler(guncelleme, baglam))
    return guncelleme.message.gonderilen


def test_duz_mesaj_cevap_aliyor(sohbet):
    """'merhaba' yazinca bir cevap donmeli -- istisna firlatmadan."""
    v, cagrilar, _ = sohbet
    cevaplar = _gonder(v, "merhaba")

    assert cagrilar == ["merhaba"], "model hic cagrilmadi"
    assert cevaplar, "kullaniciya hicbir sey gonderilmedi"
    assert "selam, buradayim" in cevaplar[-1]


def test_mesaj_logu_maskeli_ve_icerik_yok(sohbet):
    v, _, topla = sohbet
    _gonder(v, "gizli bir cumle")

    satir = next(s for s in topla.satirlar if "Mesaj alındı" in s)
    assert "***456" in satir
    assert "123456" not in satir
    assert "gizli" not in satir, f"Mesaj icerigi loga girdi: {satir}"


def test_mesaj_islenirken_hata_logu_yok(sohbet):
    """Cevap gitse bile arada yutulmus bir hata olmamali."""
    v, _, topla = sohbet
    _gonder(v, "merhaba")
    hatalar = [s for s in topla.satirlar if "kritik hatası" in s or "Traceback" in s]
    assert not hatalar, hatalar
