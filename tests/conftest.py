import importlib
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def vasi_module(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("MY_TELEGRAM_ID", "123456")
    monkeypatch.setenv("WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    # Testler .env'den BAGIMSIZ olmali. USE_LITELLM acikken calistirilan
    # bir test, gercek proxy'ye istek atmaya calisir ve ortama gore
    # farkli sonuc verir. LiteLLM yolunu test etmek isteyen testler
    # modul niteligini monkeypatch ile acar.
    monkeypatch.setenv("USE_LITELLM", "false")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PENDING_ACTION_TTL_SECONDS", "30")
    monkeypatch.setenv("GEMINI_DAILY_LIMIT_REQUESTS", "3")
    monkeypatch.delenv("WEB_RADAR_ALLOWLIST", raising=False)

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Depo kokundeki TUM yerel modulleri bellekten temizle.
    #
    # Neden elle liste tutmuyoruz: bu liste bir kez elle yazildi ve
    # decision.py eklendiginde guncellenmeyi unuttu. Onbellekte kalan
    # bir modul, eski ortam degiskenlerini sonraki testlere tasir ve
    # bunu hicbir test yakalamaz. Kok dizini taramak, yeni bir katman
    # eklendiginde kendiliginde kapsar.
    for py_dosya in repo_root.glob("*.py"):
        modul = py_dosya.stem
        if modul in sys.modules:
            del sys.modules[modul]

    module = importlib.import_module("vasi")

    module.USER_RATE_LIMITS.clear()
    module.GEMINI_RATE_LIMITS.clear()
    module.GEMINI_DAILY_COUNTERS.clear()
    return module