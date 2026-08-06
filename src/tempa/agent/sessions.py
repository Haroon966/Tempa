"""Persist Cursor agent ids per channel thread (resume across turns)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_lock = threading.Lock()


def _path() -> Path:
    p = get_settings().sessions_dir / "tempa_agent" / "sessions.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def thread_key(*, channel: str, thread_id: str) -> str:
    return f"{(channel or '').strip()}|{(thread_id or '').strip()}"


def _read() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict[str, Any]) -> None:
    path = _path()
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def get_session(*, channel: str, thread_id: str) -> dict[str, Any] | None:
    key = thread_key(channel=channel, thread_id=thread_id)
    with _lock:
        row = _read().get(key)
    return dict(row) if isinstance(row, dict) else None


def save_session(
    *,
    channel: str,
    thread_id: str,
    agent_id: str,
    local_cwd: str = "",
    repo: str = "",
    user_id: str = "",
) -> None:
    key = thread_key(channel=channel, thread_id=thread_id)
    with _lock:
        data = _read()
        data[key] = {
            "channel": channel,
            "thread_id": thread_id,
            "agent_id": agent_id,
            "local_cwd": local_cwd,
            "repo": repo,
            "user_id": user_id,
        }
        _write(data)


def clear_session(*, channel: str, thread_id: str) -> None:
    key = thread_key(channel=channel, thread_id=thread_id)
    with _lock:
        data = _read()
        data.pop(key, None)
        _write(data)
