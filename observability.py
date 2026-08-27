import json
import logging
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class HealthCheck:
    component: str
    status: str
    latency_ms: int | None = None
    details: str = ""
    error: str = ""


class ObservabilityStore:
    def __init__(self, logger: logging.Logger, max_events: int = 500) -> None:
        self.logger = logger
        self.events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self.command_counts: Counter[str] = Counter()
        self.error_counts: Counter[str] = Counter()
        self.model_latency_ms: Counter[str] = Counter()
        self.model_calls: Counter[str] = Counter()
        self.last_command_at: datetime | None = None
        self.last_command_name: str | None = None

    def structured_event(self, event: str, **fields: Any) -> None:
        payload = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        self.events.append(payload)
        self.logger.info("OBSERVABILITY %s", json.dumps(payload, ensure_ascii=False, default=str))

    def record_command(self, command: str, duration_ms: int, ok: bool, error: str = "") -> None:
        self.command_counts[command] += 1
        self.last_command_name = command
        self.last_command_at = datetime.now(timezone.utc)
        if not ok:
            self.error_counts[command] += 1
        self.structured_event(
            "command.completed",
            command=command,
            duration_ms=duration_ms,
            ok=ok,
            error=error[:160],
        )

    def record_model_call(self, model: str, duration_ms: int, ok: bool, error: str = "") -> None:
        self.model_calls[model] += 1
        self.model_latency_ms[model] += duration_ms
        if not ok:
            self.error_counts[f"model:{model}"] += 1
        self.structured_event(
            "model.completed",
            model=model,
            duration_ms=duration_ms,
            ok=ok,
            error=error[:160],
        )

    def record_audit(self, event: str, user_id: str, detail: str) -> None:
        self.structured_event(
            "audit",
            audit_event=event,
            user_id=mask_user_id(user_id),
            detail=detail[:240],
        )

    def last_command_summary(self) -> str:
        if not self.last_command_at or not self.last_command_name:
            return "henüz yok"
        age_seconds = int((datetime.now(timezone.utc) - self.last_command_at).total_seconds())
        if age_seconds < 60:
            age = f"{age_seconds} sn önce"
        else:
            age = f"{age_seconds // 60} dk önce"
        return f"/{self.last_command_name} ({age})"

    def format_statistics_report(self, checked_at: datetime | None = None) -> str:
        now = checked_at or datetime.now()
        lines = [
            f"İstatistik — {now.strftime('%H:%M')}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Toplam komut: {sum(self.command_counts.values())}",
            f"Toplam hata: {sum(self.error_counts.values())}",
            f"Son komut: {self.last_command_summary()}",
            "",
            "En çok kullanılan komutlar:",
        ]
        lines.extend(format_counter_lines(self.command_counts, prefix="/"))
        lines.extend(["", "Model ortalama süreleri:"])
        lines.extend(format_model_latency_lines(self.model_calls, self.model_latency_ms))
        lines.extend(["", "Hata dağılımı:"])
        lines.extend(format_counter_lines(self.error_counts))
        return "\n".join(lines)

    def format_audit_summary(self, checked_at: datetime | None = None, limit: int = 8) -> str:
        now = checked_at or datetime.now()
        event_counts = Counter(str(event.get("event", "unknown")) for event in self.events)
        audit_events = [event for event in self.events if event.get("event") == "audit"]
        recent_events = list(self.events)[-limit:]
        lines = [
            f"Audit özeti — {now.strftime('%H:%M')}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Bellekteki olay: {len(self.events)}",
            f"Audit olayı: {len(audit_events)}",
            f"Son komut: {self.last_command_summary()}",
            "",
            "Olay türleri:",
        ]
        lines.extend(format_counter_lines(event_counts))
        lines.extend(["", "Son olaylar:"])
        lines.extend(format_recent_event_lines(recent_events))
        lines.extend(["", "Son audit olayları:"])
        lines.extend(format_recent_audit_lines(audit_events[-limit:]))
        return "\n".join(lines)


def mask_user_id(user_id: str) -> str:
    if not user_id:
        return "***"
    return f"***{user_id[-3:]}" if len(user_id) > 3 else "***"


def format_counter_lines(counter: Counter[str], prefix: str = "") -> list[str]:
    if not counter:
        return ["- henüz veri yok"]
    return [f"- {prefix}{name}: {count}" for name, count in counter.most_common(5)]


def format_model_latency_lines(model_calls: Counter[str], model_latency_ms: Counter[str]) -> list[str]:
    if not model_calls:
        return ["- henüz model çağrısı yok"]
    lines = []
    for model, count in model_calls.most_common(5):
        avg_ms = int(model_latency_ms[model] / count) if count else 0
        lines.append(f"- {model}: {avg_ms}ms ortalama ({count} çağrı)")
    return lines


def format_recent_event_lines(events: list[dict[str, Any]]) -> list[str]:
    if not events:
        return ["- henüz olay yok"]
    lines = []
    for event in reversed(events):
        event_name = event.get("event", "unknown")
        if event_name == "command.completed":
            status = "ok" if event.get("ok") else "hata"
            lines.append(f"- command /{event.get('command', '?')} {status} {event.get('duration_ms', '?')}ms")
        elif event_name == "model.completed":
            status = "ok" if event.get("ok") else "hata"
            lines.append(f"- model {event.get('model', '?')} {status} {event.get('duration_ms', '?')}ms")
        elif event_name == "audit":
            lines.append(f"- audit {event.get('audit_event', '?')} user={event.get('user_id', '***')}")
        else:
            lines.append(f"- {event_name}")
    return lines


def format_recent_audit_lines(events: list[dict[str, Any]]) -> list[str]:
    if not events:
        return ["- henüz audit olayı yok"]
    lines = []
    for event in reversed(events):
        detail = str(event.get("detail", "")).strip()
        suffix = f" — {detail}" if detail else ""
        lines.append(f"- {event.get('audit_event', '?')} user={event.get('user_id', '***')}{suffix}")
    return lines


def timed_check(component: str, check: Callable[[], str]) -> HealthCheck:
    started = time.perf_counter()
    try:
        details = check()
        return HealthCheck(component, "ok", int((time.perf_counter() - started) * 1000), details)
    except Exception as exc:
        return HealthCheck(
            component,
            "error",
            int((time.perf_counter() - started) * 1000),
            error=str(exc)[:220],
        )


def format_health_report(checks: list[HealthCheck], last_command: str, checked_at: datetime | None = None) -> str:
    now = checked_at or datetime.now()
    lines = [
        f"Sistem durumu — {now.strftime('%H:%M')}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for check in checks:
        icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(check.status, "•")
        latency = f" ({check.latency_ms}ms)" if check.latency_ms is not None else ""
        detail = f" {check.details}" if check.details else ""
        error = f" — {check.error}" if check.error else ""
        lines.append(f"{icon} {check.component:<14} {detail}{latency}{error}".rstrip())
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"Son komut: {last_command}",
    ])
    return "\n".join(lines)


def workspace_health(workspace: Path) -> HealthCheck:
    def check() -> str:
        if not workspace.exists():
            raise FileNotFoundError(str(workspace))
        file_count = sum(1 for path in workspace.rglob("*") if path.is_file())
        write_state = "yazılabilir" if workspace.is_dir() else "erişilebilir"
        return f"{write_state} ({file_count} dosya)"

    return timed_check("Workspace", check)


def skills_health(workspace: Path) -> HealthCheck:
    def check() -> str:
        skills_dir = workspace / "skills"
        if not skills_dir.exists():
            raise FileNotFoundError(str(skills_dir))
        skill_count = len(list(skills_dir.glob("*.md")))
        if skill_count == 0:
            return "skill bulunamadı"
        return f"{skill_count} skill yüklü"

    result = timed_check("Skills", check)
    if result.status == "ok" and result.details == "skill bulunamadı":
        return HealthCheck(result.component, "warn", result.latency_ms, result.details)
    return result
