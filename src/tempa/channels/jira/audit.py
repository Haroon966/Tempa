from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings


def _audit_path() -> Path:
    path = get_settings().sessions_dir / "jira" / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_ticket_event(
    *,
    action: str,
    requester: str,
    assignee: str = "",
    issue_key: str = "",
    channel: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "requester": requester,
        "assignee": assignee,
        "issue_key": issue_key,
        "channel": channel,
    }
    if details:
        row["details"] = details
    with _audit_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
