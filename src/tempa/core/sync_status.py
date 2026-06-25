from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}


def _state_path() -> Path:
    path = get_settings().sessions_dir / "sync_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> dict[str, dict[str, Any]]:
    global _state
    path = _state_path()
    if not path.exists():
        _state = {}
        return _state
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _state = data
            return _state
    except Exception as exc:
        logger.warning("Failed to load sync status: %s", exc)
    _state = {}
    return _state


def _save() -> None:
    path = _state_path()
    path.write_text(json.dumps(_state, ensure_ascii=False, indent=2), encoding="utf-8")


def record_sync(channel: str, *, status: str, error: str = "", details: dict[str, Any] | None = None) -> None:
    with _lock:
        _load()
        row = _state.get(channel, {})
        now = datetime.now(timezone.utc).isoformat()
        row["last_sync_at"] = now if status == "ok" else row.get("last_sync_at", "")
        row["last_attempt_at"] = now
        row["sync_status"] = status
        row["last_sync_error"] = error if status != "ok" else ""
        if details:
            row["details"] = details
        _state[channel] = row
        _save()


def get_sync_status(channel: str) -> dict[str, Any]:
    with _lock:
        _load()
        return dict(_state.get(channel, {}))


def all_sync_status() -> dict[str, dict[str, Any]]:
    with _lock:
        _load()
        return {k: dict(v) for k, v in _state.items()}
