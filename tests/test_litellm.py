"""LiteLLM backend'i ve iki API'nin normallestirilmesi.

Bu testler gercek HTTP cagrisi yapmaz; requests.post sahte bir
nesneyle degistirilir. Amac, OpenAI uyumlu yanit yapisinin dogru
ayristirildigini dogrulamak.
"""
import asyncio
import json

import pytest


# ── Arac cagri normallestirmesi ──────────────────────────────────────────────

def test_ollama_formati_normalize_ediliyor(vasi_module):
    """Ollama: arguments bir sozluk, id yok."""
    ex = vasi_module.execution
    mesaj = {
        "tool_calls": [
            {"function": {"name": "skill_get_time", "arguments": {"tz": "TR"}}}
        ]
    }
    sonuc = ex._normalize_tool_calls(mesaj)
    assert sonuc == [{"id": None, "name": "skill_get_time", "arguments": {"tz": "TR"}}]


def test_openai_formati_normalize_ediliyor(vasi_module):
    """OpenAI: arguments JSON metni, id var."""
    ex = vasi_module.execution
    mesaj = {
        "tool_calls": [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "skill_web_radar",
                    "arguments": json.dumps({"url": "https://example.com"}),
                },
            }
        ]
    }
    sonuc = ex._normalize_tool_calls(mesaj)
    assert sonuc == [
        {
            "id": "call_abc123",
            "name": "skill_web_radar",
            "arguments": {"url": "https://example.com"},
        }
    ]


def test_bozuk_json_argumani_bos_sozluge_duser(vasi_module):
    """Ayristirilamayan arguman, cagriyi patlatmamali."""
    ex = vasi_module.execution
    mesaj = {"tool_calls": [{"function": {"name": "x", "arguments": "{bozuk"}}]}
    assert ex._normalize_tool_calls(mesaj)[0]["arguments"] == {}


def test_arac_cagrisi_yoksa_bos_liste(vasi_module):
    ex = vasi_module.execution
    assert ex._normalize_tool_calls({"content": "sadece metin"}) == []
    assert ex._normalize_tool_calls({"tool_calls": None}) == []


# ── Arac sonucu paketleme ────────────────────────────────────────────────────

def test_tool_call_id_varsa_ekleniyor(vasi_module):
    """OpenAI uyumlu API tool_call_id bekler."""
    ex = vasi_module.execution
    cagri = {"id": "call_1", "name": "skill_get_time", "arguments": {}}
    mesaj = ex._tool_result_message(cagri, "12:00")
    assert mesaj["tool_call_id"] == "call_1"
    assert mesaj["name"] == "skill_get_time"
    assert mesaj["role"] == "tool"


def test_tool_call_id_yoksa_eklenmiyor(vasi_module):
    """Ollama id gondermez; alan hic olmamali."""
    ex = vasi_module.execution
    cagri = {"id": None, "name": "skill_get_time", "arguments": {}}
    mesaj = ex._tool_result_message(cagri, "12:00")
    assert "tool_call_id" not in mesaj
    assert mesaj["name"] == "skill_get_time"


# ── LiteLLM backend'i ────────────────────────────────────────────────────────

class SahteYanit:
    def __init__(self, durum=200, govde=None, metin=""):
        self.status_code = durum
        self._govde = govde or {}
        self.text = metin

    def json(self):
        return self._govde


def test_litellm_yanitindan_mesaj_cikariliyor(vasi_module, monkeypatch):
    ex = vasi_module.execution
    yakalanan = {}

    def sahte_post(url, **kw):
        yakalanan["url"] = url
        yakalanan["payload"] = kw.get("json")
        yakalanan["headers"] = kw.get("headers")
        return SahteYanit(
            govde={"choices": [{"message": {"content": "litellm cevabi"}}]}
        )

    monkeypatch.setattr(ex.requests, "post", sahte_post)
    mesaj = ex._chat_litellm("yerel-genel", [{"role": "user", "content": "selam"}])

    assert mesaj["content"] == "litellm cevabi"
    assert yakalanan["url"].endswith("/v1/chat/completions")
    assert yakalanan["payload"]["model"] == "yerel-genel"
    assert yakalanan["headers"]["Authorization"].startswith("Bearer ")


def test_litellm_hata_kodu_chatbackenderror_a_donusuyor(vasi_module, monkeypatch):
    ex = vasi_module.execution
    monkeypatch.setattr(
        ex.requests, "post",
        lambda url, **kw: SahteYanit(durum=404, metin="model yok")
    )
    with pytest.raises(ex.ChatBackendError) as hata:
        ex._chat_litellm("olmayan", [{"role": "user", "content": "x"}])
    assert hata.value.status_code == 404


def test_litellm_baglanti_hatasi_yakalaniyor(vasi_module, monkeypatch):
    ex = vasi_module.execution

    def patlayan_post(url, **kw):
        raise ex.requests.RequestException("baglanti yok")

    monkeypatch.setattr(ex.requests, "post", patlayan_post)
    with pytest.raises(ex.ChatBackendError):
        ex._chat_litellm("yerel-genel", [{"role": "user", "content": "x"}])


# ── Bayrak davranisi ─────────────────────────────────────────────────────────

def test_varsayilan_backend_ollama(vasi_module):
    """USE_LITELLM ayarlanmadiysa davranis degismemeli."""
    assert vasi_module.execution.USE_LITELLM is False


def test_bayrak_acikken_litellm_secilir(vasi_module, monkeypatch):
    ex = vasi_module.execution
    monkeypatch.setattr(ex, "USE_LITELLM", True)
    monkeypatch.setattr(
        ex.requests, "post",
        lambda url, **kw: SahteYanit(
            govde={"choices": [{"message": {"content": "proxy uzerinden"}}]}
        ),
    )
    sonuc = asyncio.run(ex.run_model_with_tools("yerel-genel", "selam"))
    assert sonuc == "proxy uzerinden"


def test_bayrak_kapaliyken_ollama_secilir(vasi_module, monkeypatch):
    ex = vasi_module.execution
    monkeypatch.setattr(
        ex.ollama_client, "chat",
        lambda **kw: {"message": {"content": "ollama uzerinden"}},
    )
    sonuc = asyncio.run(ex.run_model_with_tools("qwen3:30b", "selam"))
    assert sonuc == "ollama uzerinden"


# ── Rol → model eslesmesi ────────────────────────────────────────────────────

def test_bayrak_kapaliyken_ollama_adi_dondurulur(vasi_module):
    d = vasi_module.decision
    assert d.model_for_role("kod") == d.MODELS["kod"]
    assert not d.model_for_role("kod").startswith("yerel-")


def test_bayrak_acikken_takma_ad_dondurulur(vasi_module, monkeypatch):
    d = vasi_module.decision
    monkeypatch.setattr(d, "_USE_LITELLM", True)
    assert d.model_for_role("kod") == "yerel-kod"
    assert d.model_for_role("gatekeeper") == "yerel-genel"


def test_takma_adlar_gizlilik_kuralina_uyuyor(vasi_module):
    """LITELLM_ALIASES icindeki her ad onek kuralina uymali."""
    d = vasi_module.decision
    for rol, ad in d.LITELLM_ALIASES.items():
        assert d.privacy_profile(ad) != "bilinmiyor", (
            f"'{rol}' rolu icin '{ad}' onek kuralina uymuyor"
        )


def test_bilinmeyen_rol_yerel_genele_duser(vasi_module, monkeypatch):
    """Guvenli varsayilan: tanimsiz rol dis modele gitmemeli."""
    d = vasi_module.decision
    monkeypatch.setattr(d, "_USE_LITELLM", True)
    assert d.model_for_role("tanimsiz_rol") == "yerel-genel"
    assert d.is_local(d.model_for_role("tanimsiz_rol"))


def test_testler_env_dosyasindan_bagimsiz(vasi_module):
    """conftest USE_LITELLM'i acikca kapatmali.

    Aksi halde .env'de bayrak acikken calistirilan testler gercek
    proxy'ye istek atar ve sonuc ortama gore degisir. Bir test
    paketi, calistirildigi makineye gore farkli sonuc vermemeli.
    """
    import os
    assert os.environ.get("USE_LITELLM") == "false", (
        "conftest USE_LITELLM'i ayarlamiyor; testler .env'e bagimli hale gelir"
    )