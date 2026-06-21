"""Thread-safe registry of active Meet Playwright sessions."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class ActiveMeetSession:
    meeting_id: str
    page: Any
    meet_url: str
    title: str


_lock = threading.Lock()
_sessions: dict[str, ActiveMeetSession] = {}


def register_session(meeting_id: str, page: Any, *, meet_url: str = "", title: str = "") -> None:
    with _lock:
        _sessions[meeting_id] = ActiveMeetSession(
            meeting_id=meeting_id,
            page=page,
            meet_url=meet_url,
            title=title,
        )


def unregister_session(meeting_id: str) -> None:
    with _lock:
        _sessions.pop(meeting_id, None)


def get_session(meeting_id: str) -> ActiveMeetSession | None:
    with _lock:
        return _sessions.get(meeting_id)


def list_active_sessions() -> list[dict[str, str]]:
    with _lock:
        return [
            {"meeting_id": s.meeting_id, "meet_url": s.meet_url, "title": s.title}
            for s in _sessions.values()
        ]
