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
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PENDING_ACTION_TTL_SECONDS", "30")
    monkeypatch.setenv("GEMINI_DAILY_LIMIT_REQUESTS", "3")
    monkeypatch.delenv("WEB_RADAR_ALLOWLIST", raising=False)

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    if "vasi" in sys.modules:
        del sys.modules["vasi"]
    module = importlib.import_module("vasi")

    module.USER_RATE_LIMITS.clear()
    module.GEMINI_RATE_LIMITS.clear()
    module.GEMINI_DAILY_COUNTERS.clear()
    return module
