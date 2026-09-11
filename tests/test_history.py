"""Konusma gecmisi: budama, siniflar ve guvenlik kurallari.

Temel kural: gecmise yalnizca kullanici mesaji ve modelin NIHAI metin
cevabi girer. Arac sonuclari GIRMEZ -- cunku bir web sayfasindaki
gizli talimat gecmise girerse, tek seferlik bir enjeksiyon kalici
bir enjeksiyona donusur.
"""
import asyncio
import inspect

import pytest


# ── Budama ───────────────────────────────────────────────────────────────────

def test_bos_gecmise_tur_eklenebiliyor(vasi_module):
    c = vasi_module.context
    g = c.append_turn([], "merhaba", "selam")
    assert g == [
        {"role": "user", "content": "merhaba"},
        {"role": "assistant", "content": "selam"},
    ]


def test_gecmis_sinirda_buduniyor(vasi_module):
    """MAX_HISTORY_TURNS asildiginda en eski turlar atilir."""
    c = vasi_module.context
    g = []
    for i in range(c.MAX_HISTORY_TURNS + 5):
        g = c.append_turn(g, f"soru{i}", f"cevap{i}")

    assert len(g) == c.MAX_HISTORY_TURNS * 2
    assert g[-1]["content"] == f"cevap{c.MAX_HISTORY_TURNS + 4}"
    assert "soru0" not in [m["content"] for m in g]


def test_budama_tur_butunlugunu_koruyor(vasi_module):
    """Gecmis her zaman kullanici/model cifti seklinde kalmali."""
    c = vasi_module.context
    g = []
    for i in range(c.MAX_HISTORY_TURNS + 3):
        g = c.append_turn(g, f"s{i}", f"c{i}")

    assert g[0]["role"] == "user"
    assert g[-1]["role"] == "assistant"
    for i in range(0, len(g), 2):
        assert g[i]["role"] == "user"
        assert g[i + 1]["role"] == "assistant"


def test_append_turn_orijinali_degistirmiyor(vasi_module):
    """Saf fonksiyon: girdi listesi bozulmamali."""
    c = vasi_module.context
    orijinal = [{"role": "user", "content": "eski"}]
    c.append_turn(orijinal, "yeni", "cevap")
    assert len(orijinal) == 1


# ── Modele gonderim ──────────────────────────────────────────────────────────

def test_gecmis_mesajlara_ekleniyor(vasi_module, monkeypatch):
    ex = vasi_module.execution
    yakalanan = {}

    def sahte_chat(model, messages, tools=None, options=None):
        yakalanan["messages"] = messages
        return {"content": "tamam"}

    monkeypatch.setattr(ex, "_chat", sahte_chat)
    gecmis = [
        {"role": "user", "content": "bana Patron de"},
        {"role": "assistant", "content": "Tamam Patron."},
    ]
    asyncio.run(ex.run_model_with_tools(
        "yerel-genel", "nasil hitap ediyordun?", "sistem", history=gecmis
    ))

    roller = [m["role"] for m in yakalanan["messages"]]
    assert roller == ["system", "user", "assistant", "user"]
    assert yakalanan["messages"][1]["content"] == "bana Patron de"


def test_gecmis_yoksa_sadece_sistem_ve_kullanici(vasi_module, monkeypatch):
    ex = vasi_module.execution
    yakalanan = {}
    monkeypatch.setattr(
        ex, "_chat",
        lambda m, msgs, **kw: (yakalanan.update(messages=msgs), {"content": "ok"})[1]
    )
    asyncio.run(ex.run_model_with_tools("yerel-genel", "merhaba", "sistem"))
    assert [m["role"] for m in yakalanan["messages"]] == ["system", "user"]


# ── GUVENLIK: arac sonuclari gecmise girmemeli ───────────────────────────────

def test_arac_sonuclari_gecmise_girmiyor(vasi_module):
    """KRITIK: append_turn yalnizca iki mesaj ekler.

    Arac sonuclari (web icerigi, dosya icerigi) gecmise girerse,
    o icerikteki gizli bir talimat sonraki HER turda modele tekrar
    gonderilir. Tek seferlik enjeksiyon, kalici hale gelir.
    """
    c = vasi_module.context
    g = c.append_turn([], "sayfayi oku", "Sayfa ozeti: ...")
    assert len(g) == 2
    assert all(m["role"] in ("user", "assistant") for m in g)
    assert not any(m["role"] == "tool" for m in g)


def test_append_turn_sadece_iki_parametre_aliyor(vasi_module):
    """Imza degisirse (ornegin arac sonucu eklenirse) bu test uyarir."""
    c = vasi_module.context
    sig = inspect.signature(c.append_turn)
    assert list(sig.parameters) == ["gecmis", "kullanici", "model_cevabi"]


def test_message_handler_gecmisi_sadece_basarida_kaydediyor(vasi_module):
    """Hata durumunda gecmis kirlenmemeli."""
    kaynak = inspect.getsource(vasi_module.message_handler)
    kayit = kaynak.index('context.user_data["sohbet_gecmisi"] = append_turn')
    try_blok = kaynak.index("try:")
    ilk_except = kaynak.index("except")
    assert try_blok < kayit < ilk_except, (
        "gecmis kaydi try blogunun icinde ve except'ten once olmali"
    )


# ── /temizle komutu ──────────────────────────────────────────────────────────

def test_temizle_komutu_var(vasi_module):
    assert hasattr(vasi_module, "cmd_temizle")
    assert inspect.iscoroutinefunction(vasi_module.cmd_temizle)


def test_temizle_yardim_metninde(vasi_module):
    assert "/temizle" in vasi_module.HELP_TEXT


def test_temizle_audit_izi_birakiyor(vasi_module):
    """Gecmis silme denetlenebilir olmali."""
    kaynak = inspect.getsource(vasi_module.cmd_temizle)
    assert "audit_event(" in kaynak
    assert "history_cleared" in kaynak