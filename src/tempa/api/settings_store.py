from __future__ import annotations

import json
from pathlib import Path

from tempa.settings import get_settings

_KEYS = (
    "reminder_minutes_before",
    "meet_auto_join_on_reminder",
    "meet_auto_join_enabled",
    "meet_trigger_before_minutes",
    "meet_trigger_after_start_minutes",
    "meet_alone_grace_seconds",
    "meet_skip_keywords",
    "meet_retention_days",
    "meet_auto_send_summary_whatsapp",
    "meet_copilot_whatsapp_notify",
)


def _path() -> Path:
    return get_settings().sessions_dir / "daemon_settings.json"


def load_daemon_settings() -> dict:
    path = _path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_daemon_settings(updates: dict) -> dict:
    data = load_daemon_settings()
    data.update({k: v for k, v in updates.items() if k in _KEYS and v is not None})
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def apply_daemon_settings() -> None:
    from tempa.settings import get_settings

    settings = get_settings()
    for key, value in load_daemon_settings().items():
        if key in _KEYS and hasattr(settings, key):
            setattr(settings, key, value)


def get_public_settings() -> dict:
    settings = get_settings()
    return {
        "reminder_minutes_before": settings.reminder_minutes_before,
        "meet_auto_join_on_reminder": settings.meet_auto_join_on_reminder,
        "meet_auto_join_enabled": settings.meet_auto_join_enabled,
        "meet_trigger_before_minutes": settings.meet_trigger_before_minutes,
        "meet_trigger_after_start_minutes": settings.meet_trigger_after_start_minutes,
        "meet_alone_grace_seconds": settings.meet_alone_grace_seconds,
        "meet_skip_keywords": settings.meet_skip_keywords,
        "meet_retention_days": settings.meet_retention_days,
        "meet_auto_send_summary_whatsapp": settings.meet_auto_send_summary_whatsapp,
        "meet_copilot_whatsapp_notify": settings.meet_copilot_whatsapp_notify,
        "tempa_daemon_port": settings.tempa_daemon_port,
    }
