"""Bu oturumda yapilan degisiklikleri dogrulayan testler."""
import asyncio
import inspect


# ── /siniflandir komutu ve veri siniflandirma ────────────────────────────────

def test_siniflandir_komutu_var(vasi_module):
    assert hasattr(vasi_module, "cmd_siniflandir")
    assert inspect.iscoroutinefunction(vasi_module.cmd_siniflandir)


def test_siniflandir_yardim_metninde(vasi_module):
    assert "/siniflandir" in vasi_module.HELP_TEXT


def test_classification_report_line_calisiyor(vasi_module):
    line = vasi_module.classification_report_line("notlar/NOTES.md")
    assert "notlar/NOTES.md" in line
    assert "PRIVATE" in line
    assert "kapalı" in line


def test_public_dosya_siniflandiriliyor(vasi_module):
    """PUBLIC siniflandirmasi calisiyor.

    Not: gemini_allowed degeri policy dosyasindan gelir; PUBLIC dosyalarda
    bile dosya aktarimi kapali tutulabilir (savunma katmani tercihi).
    """
    assert vasi_module.classify_file("youtube/senaryo.md") == "PUBLIC"


def test_private_dosya_gemini_kapali(vasi_module):
    assert vasi_module.classify_file("notlar/NOTES.md") == "PRIVATE"
    assert vasi_module.is_gemini_allowed("notlar/NOTES.md") is False


def test_kok_dizindeki_env_secret_olarak_siniflanir(vasi_module):
    """Duzeltilen desen bosslugu: kok dizindeki .env de SECRET olmali."""
    assert vasi_module.classify_file(".env") == "SECRET"
    assert vasi_module.is_gemini_allowed(".env") is False


def test_bilinmeyen_dosya_varsayilan_private(vasi_module):
    assert vasi_module.classify_file("rastgele.txt") == "PRIVATE"


# ── run_model_with_tools async refactor ──────────────────────────────────────

def test_run_model_with_tools_async_oldu(vasi_module):
    assert inspect.iscoroutinefunction(vasi_module.run_model_with_tools)


def test_run_model_with_tools_on_tool_use_parametresi_var(vasi_module):
    sig = inspect.signature(vasi_module.run_model_with_tools)
    assert "on_tool_use" in sig.parameters
    assert sig.parameters["on_tool_use"].default is None


def test_tool_kullanildiginda_bildirim_cagriliyor(vasi_module, monkeypatch):
    """Model arac cagirirsa on_tool_use tetiklenmeli."""
    calls = {"count": 0}

    async def fake_notify():
        calls["count"] += 1

    responses = [
        {"message": {"tool_calls": [
            {"function": {"name": "skill_get_time", "arguments": {}}}
        ]}},
        {"message": {"content": "saat soylendi"}},
    ]

    def fake_chat(**kwargs):
        return responses.pop(0)

    monkeypatch.setattr(vasi_module.ollama_client, "chat", fake_chat)

    result = asyncio.run(vasi_module.run_model_with_tools(
        "test-model", "saat kac", on_tool_use=fake_notify
    ))

    assert calls["count"] == 1
    assert result == "saat soylendi"


def test_tool_kullanilmazsa_bildirim_cagrilmiyor(vasi_module, monkeypatch):
    calls = {"count": 0}

    async def fake_notify():
        calls["count"] += 1

    def fake_chat(**kwargs):
        return {"message": {"content": "duz cevap"}}

    monkeypatch.setattr(vasi_module.ollama_client, "chat", fake_chat)

    result = asyncio.run(vasi_module.run_model_with_tools(
        "test-model", "merhaba", on_tool_use=fake_notify
    ))

    assert calls["count"] == 0
    assert result == "duz cevap"


def test_whitelist_disi_tool_reddediliyor(vasi_module, monkeypatch):
    """Guvenlik: whitelist disindaki arac calistirilmamali."""
    captured = {"messages": None}

    responses = [
        {"message": {"tool_calls": [
            {"function": {"name": "kotu_arac", "arguments": {}}}
        ]}},
        {"message": {"content": "bitti"}},
    ]

    def fake_chat(**kwargs):
        if len(responses) == 1:
            captured["messages"] = kwargs.get("messages")
        return responses.pop(0)

    monkeypatch.setattr(vasi_module.ollama_client, "chat", fake_chat)

    asyncio.run(vasi_module.run_model_with_tools("test-model", "kotu istek"))

    tool_msgs = [m for m in captured["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "yasak" in tool_msgs[0]["content"].lower()


def test_message_handler_artik_kisa(vasi_module):
    """Tekrar temizlendi: message_handler artik tool dongusunu icermemeli."""
    source = inspect.getsource(vasi_module.message_handler)
    assert "ALLOWED_TOOL_NAMES" not in source
    assert "run_model_with_tools" in source


# ── Yazma uzantisi guvencesi (fidye yazilimi katmani) ───────────────────────

def test_izinli_uzantilar_yazilabilir(vasi_module):
    for ext in [".md", ".txt", ".json", ".yaml", ".yml", ".csv"]:
        path = vasi_module.WORKSPACE / f"notlar/dosya{ext}"
        assert vasi_module.is_allowed_write_file(path), f"{ext} yazilabilir olmali"


def test_tehlikeli_uzantilar_yazilamaz(vasi_module):
    """Calistirilabilir veya betik dosyalari yazilamamali."""
    for ext in [".py", ".sh", ".exe", ".so", ".dll", ".bat", ".env"]:
        path = vasi_module.WORKSPACE / f"notlar/dosya{ext}"
        assert not vasi_module.is_allowed_write_file(path), f"{ext} engellenmeli"


def test_uzantisiz_dosya_yazilamaz(vasi_module):
    path = vasi_module.WORKSPACE / "notlar/uzantisiz"
    assert not vasi_module.is_allowed_write_file(path)


def test_uzanti_buyuk_harf_duyarsiz(vasi_module):
    """.MD ve .md ayni islem gormeli."""
    path = vasi_module.WORKSPACE / "notlar/DOSYA.MD"
    assert vasi_module.is_allowed_write_file(path)