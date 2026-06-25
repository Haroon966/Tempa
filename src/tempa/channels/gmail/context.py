from __future__ import annotations

import logging
from typing import Any

from tempa.agents.intent import is_follow_up
from tempa.channels.gmail.snapshot import load_gmail_snapshot
from tempa.core.text import truncate

logger = logging.getLogger(__name__)


def _relative_age(date_str: str) -> str:
    if not date_str:
        return ""
    return date_str[:16] if len(date_str) > 16 else date_str


def _fetch_pending_email_drafts() -> list[dict[str, Any]]:
    try:
        from tempa.core.pending_actions import list_pending_actions

        pending = list_pending_actions(status="pending")
        drafts: list[dict[str, Any]] = []
        for action in pending:
            if action.get("type") != "email_send":
                continue
            payload = action.get("payload") or {}
            drafts.append(
                {
                    "id": action.get("id", ""),
                    "to": payload.get("to", ""),
                    "subject": payload.get("subject", ""),
                    "preview": truncate(str(payload.get("body") or payload.get("preview") or ""), 300),
                }
            )
        return drafts
    except Exception as exc:
        logger.warning("Failed to load pending email drafts: %s", exc)
        return []


def _gmail_connection_status(snapshot: dict[str, Any]) -> str:
    try:
        from tempa.channels.gmail.oauth import load_gmail_client

        if load_gmail_client() is None:
            return "Gmail: not connected"
    except Exception:
        return "Gmail: not connected"
    last = snapshot.get("last_sync_at") or "never"
    return f"Gmail: connected (last sync {last})"


def _calendar_title_hints() -> set[str]:
    try:
        from tempa.channels.calendar.sync import load_calendar_snapshot

        titles = {
            str(e.get("summary", "")).lower()
            for e in (load_calendar_snapshot().get("events") or [])
            if isinstance(e, dict) and e.get("summary")
        }
        return titles
    except Exception as exc:
        logger.warning("Failed to load calendar title hints: %s", exc)
        return set()


def build_gmail_context_pack(*, include_body_snippets: bool = True) -> dict[str, Any]:
    snapshot = load_gmail_snapshot()
    inbox = list(snapshot.get("inbox") or [])
    sent = list(snapshot.get("recent_sent") or [])
    unread = [m for m in inbox if m.get("unread")]
    cal_titles = _calendar_title_hints()

    calendar_links: list[str] = []
    snippet_limit = 400 if include_body_snippets else 200
    for msg in inbox[:10]:
        subject_lower = str(msg.get("subject", "")).lower()
        for title in cal_titles:
            if title and title in subject_lower:
                calendar_links.append(
                    f"Email '{msg.get('subject')}' may relate to calendar event '{title}'"
                )
                break

    return {
        "connection_status": _gmail_connection_status(snapshot),
        "unread_count": int(snapshot.get("unread_count") or 0),
        "inbox_compact": unread[:5],
        "inbox_recent": inbox[:10],
        "recent_sent": sent[:5],
        "pending_drafts": _fetch_pending_email_drafts(),
        "calendar_links": calendar_links,
        "last_sync_at": snapshot.get("last_sync_at") or "",
        "snippet_limit": snippet_limit,
    }


def format_gmail_context_for_prompt(pack: dict[str, Any], *, compact: bool = True) -> str:
    if pack.get("connection_status", "").endswith("not connected"):
        return pack["connection_status"]

    parts: list[str] = [pack.get("connection_status") or ""]
    last_sync = pack.get("last_sync_at") or ""
    if last_sync:
        parts.append(f"Gmail snapshot as of {last_sync}")
    unread_count = int(pack.get("unread_count") or 0)
    limit = int(pack.get("snippet_limit") or 200)

    if compact:
        parts.append(f"Inbox: {unread_count} unread")
        unread = pack.get("inbox_compact") or []
        if unread:
            lines = []
            for msg in unread:
                lines.append(
                    f"- {_relative_age(str(msg.get('date', '')))} {msg.get('from', '?')}: "
                    f"{msg.get('subject', '?')}"
                )
            parts.append("Unread:\n" + "\n".join(lines))
        elif unread_count == 0:
            parts.append("No unread messages in snapshot.")
    else:
        parts.append(f"Inbox: {unread_count} unread")
        inbox = pack.get("inbox_recent") or []
        if inbox:
            lines = []
            for msg in inbox:
                flag = " [unread]" if msg.get("unread") else ""
                snippet = truncate(str(msg.get("snippet") or ""), limit)
                line = (
                    f"- {_relative_age(str(msg.get('date', '')))} {msg.get('from', '?')}: "
                    f"{msg.get('subject', '?')}{flag}"
                )
                if snippet:
                    line += f" — {truncate(snippet, limit)}"
                lines.append(line)
            parts.append("Recent inbox:\n" + "\n".join(lines))

        sent = pack.get("recent_sent") or []
        if sent:
            lines = []
            for msg in sent:
                lines.append(
                    f"- {_relative_age(str(msg.get('date', '')))} to {msg.get('to', '?')}: "
                    f"{msg.get('subject', '?')}"
                )
            parts.append("Recent sent:\n" + "\n".join(lines))

        drafts = pack.get("pending_drafts") or []
        if drafts:
            lines = []
            for d in drafts:
                lines.append(
                    f"- Draft to {d.get('to', '?')}: {d.get('subject', '?')} — {d.get('preview', '')}"
                )
            parts.append("Pending email drafts:\n" + "\n".join(lines))

        links = pack.get("calendar_links") or []
        if links:
            parts.append("Calendar links:\n" + "\n".join(f"- {link}" for link in links[:5]))

    return "\n\n".join(p for p in parts if p)
