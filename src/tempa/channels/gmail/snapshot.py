from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.gmail.client import GmailMessage
from tempa.channels.gmail.oauth import load_gmail_client
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def _snapshot_path() -> Path:
    path = get_settings().sessions_dir / "gmail" / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_gmail_snapshot() -> dict[str, Any]:
    path = _snapshot_path()
    if not path.exists():
        return {"inbox": [], "recent_sent": [], "unread_count": 0, "last_sync_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"inbox": [], "recent_sent": [], "unread_count": 0, "last_sync_at": ""}


def save_gmail_snapshot(data: dict[str, Any]) -> None:
    _snapshot_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _message_to_inbox_row(msg: GmailMessage) -> dict[str, Any]:
    labels = list(msg.label_ids or [])
    return {
        "id": msg.id,
        "thread_id": msg.thread_id,
        "from": msg.sender,
        "subject": msg.subject or "(no subject)",
        "date": msg.date,
        "snippet": (msg.snippet or msg.body_text or "")[:400],
        "unread": "UNREAD" in labels,
        "labels": labels,
    }


def _message_to_sent_row(msg: GmailMessage) -> dict[str, Any]:
    return {
        "id": msg.id,
        "thread_id": msg.thread_id,
        "to": msg.to,
        "subject": msg.subject or "(no subject)",
        "date": msg.date,
        "snippet": (msg.snippet or msg.body_text or "")[:400],
    }


def refresh_gmail_snapshot(
    *,
    inbox_limit: int = 15,
    sent_limit: int = 5,
) -> dict[str, Any]:
    """Fetch recent inbox/sent metadata and persist snapshot."""
    client = load_gmail_client()
    if client is None:
        return {"status": "skipped", "reason": "Gmail not connected"}

    inbox_rows: list[dict[str, Any]] = []
    sent_rows: list[dict[str, Any]] = []

    try:
        inbox_ids = client.list_messages(query="in:inbox", max_results=inbox_limit)[0]
        if inbox_ids:
            for msg in client.get_messages_metadata(inbox_ids):
                inbox_rows.append(_message_to_inbox_row(msg))
    except Exception:
        logger.exception("Gmail inbox snapshot fetch failed")

    try:
        sent_ids = client.list_messages(query="in:sent", max_results=sent_limit)[0]
        if sent_ids:
            for msg in client.get_messages_metadata(sent_ids):
                sent_rows.append(_message_to_sent_row(msg))
    except Exception:
        logger.exception("Gmail sent snapshot fetch failed")

    unread_count = sum(1 for row in inbox_rows if row.get("unread"))
    try:
        profile = client.get_profile()
        unread_count = int(profile.get("messagesUnread") or unread_count)
    except Exception:
        logger.debug("Gmail profile unread count unavailable", exc_info=True)

    snapshot = {
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
        "unread_count": unread_count,
        "inbox": inbox_rows,
        "recent_sent": sent_rows,
    }
    save_gmail_snapshot(snapshot)
    return {"status": "ok", "unread_count": unread_count, "inbox": len(inbox_rows), "sent": len(sent_rows)}
