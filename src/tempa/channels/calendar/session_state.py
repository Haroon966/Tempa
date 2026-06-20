from __future__ import annotations

from typing import Any

_last_event: dict[str, Any] = {}


def record_calendar_event(action: dict[str, Any]) -> None:
    global _last_event
    _last_event = dict(action)


def get_last_calendar_event() -> dict[str, Any]:
    return dict(_last_event)
