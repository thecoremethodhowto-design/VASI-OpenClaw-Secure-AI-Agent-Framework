"""Taninmayan komutlarin modele dusmemesi.

Bu handler olmadan yanlis yazilmis bir komut SESSIZCE modele duser
ve model boslugu doldurur: "Bu bilgiyi not aldim" der ama hicbir sey
kaydedilmez. Tam olarak bu yasandi -- Turkce klavyede /hatırla yazmak
son derece dogal bir refleks, ve Telegram komut adlarinda Turkce
karakter kabul etmiyor.
"""
import inspect

import pytest


# ── Turkce karakter normallestirme ───────────────────────────────────────────

@pytest.mark.parametrize("yazilan,beklenen", [
    ("hatırla", "hatirla"),
    ("hatırlananlar", "hatirlananlar"),
    ("HATIRLA", "hatirla"),
    ("İstatistik", "istatistik"),
    ("güvenlik", "guvenlik"),
    ("sağlık", "saglik"),
    ("sınıflandır", "siniflandir"),
    ("temizle", "temizle"),
])
def test_turkce_karakterler_normallestiriliyor(vasi_module, yazilan, beklenen):
    assert vasi_module._normalize_komut(yazilan) == beklenen


# ── Komut listesi kendini gunceller ──────────────────────────────────────────

class SahteHandlerGrubu:
    def __init__(self, handlers):
        self._h = handlers

    def values(self):
        return [self._h]


class SahteApplication:
    def __init__(self, handlers):
        self.handlers = SahteHandlerGrubu(handlers)


class SahteContext:
    def __init__(self, handlers):
        self.application = SahteApplication(handlers)


def test_kayitli_komutlar_handlerlardan_toplaniyor(vasi_module):
    """Elle liste tutulmamali; yeni komut kendiliginden kapsanmali."""
    from telegram.ext import CommandHandler

    async def sahte(update, context):
        pass

    handlers = [
        CommandHandler("hatirla", sahte),
        CommandHandler("unut", sahte),
        CommandHandler("saglik", sahte),
    ]
    komutlar = vasi_module._kayitli_komutlar(SahteContext(handlers))
    assert komutlar == {"hatirla", "unut", "saglik"}


def test_kayitli_komutlar_elle_liste_kullanmiyor(vasi_module):
    """Kaynak kodda sabit bir komut listesi olmamali.

    Elle tutulan bir liste, yeni komut eklendiginde geride kalir.
    Bu seride bir kez yasandi (conftest modul temizligi).
    """
    kaynak = inspect.getsource(vasi_module._kayitli_komutlar)
    assert "context.application.handlers" in kaynak
    assert "CommandHandler" in kaynak


# ── Handler davranisi ────────────────────────────────────────────────────────

def test_bilinmeyen_komut_audit_izi_birakiyor(vasi_module):
    kaynak = inspect.getsource(vasi_module.cmd_bilinmeyen)
    assert "audit_event(" in kaynak
    assert "unknown_command" in kaynak


def test_bilinmeyen_komut_yardima_yonlendiriyor(vasi_module):
    kaynak = inspect.getsource(vasi_module.cmd_bilinmeyen)
    assert "/yardim" in kaynak


def test_bilinmeyen_komut_oneri_sunuyor(vasi_module):
    """Yazim hatasinda en yakin komutu onermeli."""
    kaynak = inspect.getsource(vasi_module.cmd_bilinmeyen)
    assert "difflib" in kaynak or "get_close_matches" in kaynak


def test_bilinmeyen_komut_modeli_cagirmiyor(vasi_module):
    """KRITIK: taninmayan komut iceriginin modele gitmemesi.

    /sil, /unut, /hatirla gibi hassas komutlar yanlis yazildiginda
    iceriklerinin sohbet girdisi olmasi istenmez.
    """
    kaynak = inspect.getsource(vasi_module.cmd_bilinmeyen)
    assert "run_model_with_tools" not in kaynak
    assert "pick_model" not in kaynak


# ── Handler sirasi ───────────────────────────────────────────────────────────

def test_bilinmeyen_handler_message_handlerdan_once_kayitli(vasi_module):
    """Sira onemli: / ile baslayan metin once yakalanmali."""
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    i_bilinmeyen = kaynak.index("cmd_bilinmeyen))")
    i_message = kaynak.index("message_handler\n        ))")
    assert i_bilinmeyen < i_message


def test_message_handler_slash_ile_baslayani_almiyor(vasi_module):
    """message_handler'in filtresi / ile baslayan metni dislamali."""
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    i = kaynak.index("message_handler\n        ))")
    cevre = kaynak[i - 200:i]
    assert '~filters.Regex(r"^/")' in cevre