from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

DRAFT_TTL_HOURS = 24


def _drafts_dir() -> Path:
    path = get_settings().sessions_dir / "jira" / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def context_key_from_slack(channel_id: str, thread_ts: str) -> str:
    return f"slack:{channel_id}:{thread_ts}"


def context_key_from_slack_dm(channel_id: str) -> str:
    """Stable draft key for a 1:1 DM (all messages share one conversation)."""
    return f"slack:dm:{channel_id}"


def context_key_from_dashboard(session_id: str) -> str:
    return f"dashboard:{session_id}"


def _draft_path(context_key: str) -> Path:
    safe = context_key.replace("/", "_").replace(":", "_")
    return _drafts_dir() / f"{safe}.json"


def _is_expired(draft: dict[str, Any]) -> bool:
    updated = str(draft.get("updated_at") or "")
    if not updated:
        return True
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt > timedelta(hours=DRAFT_TTL_HOURS)
    except ValueError:
        return True


def load_draft(context_key: str) -> dict[str, Any] | None:
    path = _draft_path(context_key)
    if not path.exists():
        return None
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(draft, dict) or _is_expired(draft):
            path.unlink(missing_ok=True)
            return None
        return draft
    except Exception:
        return None


def save_draft(context_key: str, draft: dict[str, Any]) -> dict[str, Any]:
    draft = dict(draft)
    draft["context_key"] = context_key
    draft["updated_at"] = datetime.now(timezone.utc).isoformat()
    _draft_path(context_key).write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft


def clear_draft(context_key: str) -> None:
    _draft_path(context_key).unlink(missing_ok=True)


def has_active_draft(context_key: str) -> bool:
    draft = load_draft(context_key)
    if not draft:
        return False
    state = str(draft.get("state") or "")
    return state in {"gathering", "preview", "confirmed", "created"}


def new_draft(context_key: str, *, channel: str, requester_id: str) -> dict[str, Any]:
    return save_draft(
        context_key,
        {
            "state": "gathering",
            "channel": channel,
            "requester_id": requester_id,
            "summary": "",
            "description": "",
            "assignee_account_id": "",
            "assignee_name": "",
            "assignee_email": "",
            "reporter_account_id": "",
            "project": "",
            "priority": "",
            "labels": [],
            "issue_key": "",
            "pending_question": "",
            "ambiguous_options": [],
        },
    )
