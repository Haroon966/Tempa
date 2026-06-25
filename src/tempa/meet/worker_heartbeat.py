from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tempa.settings import get_settings


def _heartbeat_path() -> Path:
    path = get_settings().sessions_dir / "meet" / "worker_heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_worker_heartbeat(*, pid: int | None = None) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": pid,
    }
    _heartbeat_path().write_text(json.dumps(payload), encoding="utf-8")


def read_worker_heartbeat() -> dict:
    path = _heartbeat_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def worker_is_alive(*, max_age_seconds: int = 120) -> bool:
    data = read_worker_heartbeat()
    ts = data.get("timestamp")
    if not ts:
        return False
    try:
        seen = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - seen).total_seconds()
        return age <= max_age_seconds
    except Exception:
        return False
