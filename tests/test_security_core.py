from datetime import datetime, timedelta, timezone


def test_safe_path_allows_workspace_file(vasi_module):
    target = vasi_module.safe_path("notes/test.md")
    assert target is not None
    assert target.is_relative_to(vasi_module.WORKSPACE)


def test_safe_path_blocks_traversal(vasi_module):
    target = vasi_module.safe_path("../secrets.txt")
    assert target is None


def test_is_safe_url_blocks_localhost(vasi_module):
    assert not vasi_module.is_safe_url("http://localhost/admin")
    assert not vasi_module.is_safe_url("http://127.0.0.1/admin")


def test_is_safe_url_blocks_non_http(vasi_module):
    assert not vasi_module.is_safe_url("file:///etc/passwd")


def test_web_allowlist_blocks_unknown_domain(vasi_module, monkeypatch):
    monkeypatch.setattr(vasi_module, "WEB_RADAR_ALLOWLIST", ("openai.com",))
    monkeypatch.setattr(vasi_module, "is_public_hostname", lambda _: True)
    assert not vasi_module.is_safe_url("https://example.com/blog")
    assert vasi_module.is_safe_url("https://openai.com/research")


def test_pending_expired_true(vasi_module):
    old_dt = datetime.now(timezone.utc) - timedelta(seconds=31)
    assert vasi_module.is_pending_expired({"created_at": old_dt.isoformat()})


def test_pending_expired_false(vasi_module):
    fresh_dt = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert not vasi_module.is_pending_expired({"created_at": fresh_dt.isoformat()})


def test_gemini_short_window_rate_limit(vasi_module):
    user = "u1"
    assert vasi_module.check_gemini_rate_limit(user)
    assert vasi_module.check_gemini_rate_limit(user)
    assert vasi_module.check_gemini_rate_limit(user)
    assert vasi_module.check_gemini_rate_limit(user)
    assert vasi_module.check_gemini_rate_limit(user)
    assert not vasi_module.check_gemini_rate_limit(user)


def test_gemini_daily_limit(vasi_module):
    user = "u2"
    assert vasi_module.check_gemini_daily_limit(user)
    assert vasi_module.check_gemini_daily_limit(user)
    assert vasi_module.check_gemini_daily_limit(user)
    assert not vasi_module.check_gemini_daily_limit(user)
