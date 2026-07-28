from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_DRAFT_TTL_S = 30 * 60


def _drafts_dir() -> Path:
    path = get_settings().sessions_dir / "coolify" / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def context_key_from_slack(channel_id: str, thread_ts: str) -> str:
    return f"slack:{channel_id}:{thread_ts or 'root'}"


def _path_for(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return _drafts_dir() / f"{safe}.json"


def save_draft(key: str, draft: dict[str, Any]) -> None:
    draft = {**draft, "updated_at": time.time()}
    _path_for(key).write_text(json.dumps(draft, indent=2), encoding="utf-8")


def load_draft(key: str) -> dict[str, Any] | None:
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    updated = float(data.get("updated_at") or 0)
    if updated and time.time() - updated > _DRAFT_TTL_S:
        path.unlink(missing_ok=True)
        return None
    return data


def clear_draft(key: str) -> None:
    _path_for(key).unlink(missing_ok=True)


def has_active_draft(key: str) -> bool:
    return load_draft(key) is not None
