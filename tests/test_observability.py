import logging
from datetime import datetime

from observability import (
    HealthCheck,
    ObservabilityStore,
    format_health_report,
    skills_health,
    workspace_health,
)


def test_format_health_report_includes_components():
    report = format_health_report(
        [
            HealthCheck("Ollama", "ok", 12, "1 model hazır"),
            HealthCheck("PostgreSQL", "warn", details="henüz kurulmadı"),
        ],
        "henüz yok",
        checked_at=datetime(2026, 6, 1, 14, 23),
    )

    assert "Sistem durumu — 14:23" in report
    assert "Ollama" in report
    assert "1 model hazır" in report
    assert "PostgreSQL" in report
    assert "Son komut: henüz yok" in report


def test_workspace_and_skills_health(tmp_path):
    workspace = tmp_path / "workspace"
    skills = workspace / "skills"
    skills.mkdir(parents=True)
    (workspace / "not.md").write_text("not", encoding="utf-8")
    (skills / "youtube_icerik.md").write_text("# Skill", encoding="utf-8")

    workspace_result = workspace_health(workspace)
    skills_result = skills_health(workspace)

    assert workspace_result.status == "ok"
    assert "2 dosya" in workspace_result.details
    assert skills_result.status == "ok"
    assert "1 skill" in skills_result.details


def test_observability_store_records_command():
    store = ObservabilityStore(logging.getLogger("test-observability"))

    store.record_command("saglik", duration_ms=42, ok=True)

    assert store.command_counts["saglik"] == 1
    assert store.error_counts["saglik"] == 0
    assert "/saglik" in store.last_command_summary()


def test_statistics_report_includes_command_and_model_data():
    store = ObservabilityStore(logging.getLogger("test-observability"))

    store.record_command("saglik", duration_ms=42, ok=True)
    store.record_command("kod", duration_ms=120, ok=False, error="model error")
    store.record_model_call("qwen3:30b", duration_ms=900, ok=True)
    store.record_model_call("qwen3:30b", duration_ms=1100, ok=True)

    report = store.format_statistics_report(checked_at=datetime(2026, 6, 2, 11, 18))

    assert "İstatistik — 11:18" in report
    assert "Toplam komut: 2" in report
    assert "Toplam hata: 1" in report
    assert "/saglik: 1" in report
    assert "/kod: 1" in report
    assert "qwen3:30b: 1000ms ortalama" in report


def test_audit_summary_masks_user_and_lists_recent_events():
    store = ObservabilityStore(logging.getLogger("test-observability"))

    store.record_command("ekle", duration_ms=33, ok=True)
    store.record_model_call("qwen3:30b", duration_ms=700, ok=False, error="timeout")
    store.record_audit("pending_apply", "123456789", "append:notlar/NOTES.md")

    report = store.format_audit_summary(checked_at=datetime(2026, 6, 4, 9, 30))

    assert "Audit özeti — 09:30" in report
    assert "Bellekteki olay: 3" in report
    assert "Audit olayı: 1" in report
    assert "command.completed: 1" in report
    assert "model.completed: 1" in report
    assert "audit: 1" in report
    assert "user=***789" in report
    assert "123456789" not in report
    assert "append:notlar/NOTES.md" in report
