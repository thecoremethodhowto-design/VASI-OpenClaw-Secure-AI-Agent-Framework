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


def test_scope_blocks_cross_domain_access(vasi_module):
    p = vasi_module.scoped_path("youtube/senaryolar/video.md", scope="code")
    assert p is None


def test_scope_allows_code_domain_access(vasi_module):
    p = vasi_module.scoped_path("projeler/oyunlar/idea.md", scope="code")
    assert p is not None


def test_gemini_health_without_api_key_warns(vasi_module):
    result = vasi_module.build_gemini_health()
    assert result.status == "warn"
    assert "API key yok" in result.details


def test_detect_skill_youtube(vasi_module):
    skill, path = vasi_module.detect_skill("Docker güvenliği için YouTube hook yaz")
    assert skill == "youtube_icerik"
    assert path == "skills/youtube_icerik.md"


def test_detect_skill_code(vasi_module):
    skill, path = vasi_module.detect_skill("Pygame ile top yakalama oyunu kodu yaz")
    assert skill == "kod_yardimcisi"
    assert path == "skills/kod_yardimcisi.md"


def test_detect_skill_note_test_does_not_trigger_code(vasi_module):
    skill, path = vasi_module.detect_skill("Bugünkü test notu")
    assert skill == ""
    assert path == ""


def test_detect_skill_pytest_triggers_code(vasi_module):
    skill, path = vasi_module.detect_skill("safe_path için pytest testi yaz")
    assert skill == "kod_yardimcisi"
    assert path == "skills/kod_yardimcisi.md"


def test_detect_skill_research(vasi_module):
    skill, path = vasi_module.detect_skill("2026 yapay zeka trendlerini araştır")
    assert skill == "arastirma"
    assert path == "skills/arastirma.md"


def test_classify_file_defaults_to_private(vasi_module):
    assert vasi_module.classify_file("unknown/freeform.md") == "PRIVATE"


def test_classify_file_secret(vasi_module):
    assert vasi_module.classify_file(".env") == "SECRET"
    assert not vasi_module.is_gemini_allowed(".env")


def test_classify_file_private_notes(vasi_module):
    assert vasi_module.classify_file("notlar/NOTES.md") == "PRIVATE"
    assert not vasi_module.is_gemini_allowed("notlar/NOTES.md")


def test_classify_file_project(vasi_module):
    assert vasi_module.classify_file("vasi.py") == "PROJECT"
    assert not vasi_module.is_gemini_allowed("vasi.py")


def test_classify_file_public_but_gemini_file_export_closed(vasi_module):
    assert vasi_module.classify_file("youtube/senaryolar/video.md") == "PUBLIC"
    assert not vasi_module.is_gemini_allowed("youtube/senaryolar/video.md")


def test_classify_absolute_workspace_file(vasi_module):
    target = vasi_module.WORKSPACE / "notlar" / "NOTES.md"
    assert vasi_module.classify_file(target) == "PRIVATE"


def test_classification_report_line(vasi_module):
    line = vasi_module.classification_report_line("README.md")
    assert "PUBLIC" in line
    assert "Gemini dosya aktarımı: kapalı" in line
