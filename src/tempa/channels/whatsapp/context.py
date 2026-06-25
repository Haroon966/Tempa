from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from tempa.agents.intent import is_follow_up
from tempa.channels.whatsapp.conversation import get_conversation_thread
from tempa.core.text import truncate
from tempa.core.timezone import local_tz

logger = logging.getLogger(__name__)


def _format_timestamp(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(local_tz()).strftime("%H:%M")
    except Exception:
        return ""


def _is_follow_up_message(text: str) -> bool:
    lower = text.lower().strip()
    if not is_follow_up(lower):
        return False
    return any(
        hint in lower
        for hint in (
            "email",
            "mail",
            "inbox",
            "calendar",
            "meeting",
            "event",
            "that",
            "earlier",
            "you said",
            "kaun",
            "kya",
            "kab",
        )
    )


def build_whatsapp_context_pack(
    user_message: str = "",
    *,
    limit: int = 20,
    max_chars_per_msg: int = 500,
) -> dict[str, Any]:
    if _is_follow_up_message(user_message):
        limit = 30
        max_chars_per_msg = max(max_chars_per_msg, 800)

    thread = get_conversation_thread(limit, include_assistant=True)
    recent_user_only = [m.get("text", "") for m in thread if m.get("role") == "user" and m.get("text")]

    user_msgs = [m.get("text", "") for m in thread if m.get("role") == "user"][-3:]
    thread_summary = ""
    if user_msgs:
        thread_summary = f"{len(thread)} recent turns — last topics: {' | '.join(truncate(t, 80) for t in user_msgs)}"

    formatted_lines: list[str] = []
    for msg in thread:
        role = msg.get("role", "")
        text = truncate(str(msg.get("text", "")), max_chars_per_msg)
        if not text:
            continue
        if role == "owner":
            label = "You (sent)"
        elif role == "user":
            label = "Customer"
        else:
            label = "Tempa"
        ts = _format_timestamp(str(msg.get("timestamp", "")))
        prefix = f"[{ts}] " if ts else ""
        formatted_lines.append(f"{prefix}{label}: {text}")

    return {
        "recent_thread": thread,
        "formatted_thread": "\n".join(formatted_lines) if formatted_lines else "No recent messages.",
        "thread_summary": thread_summary,
        "recent_user_only": recent_user_only,
    }


def format_whatsapp_thread_for_prompt(pack: dict[str, Any], *, label: str = "WhatsApp conversation") -> str:
    body = pack.get("formatted_thread") or "No recent messages."
    summary = pack.get("thread_summary") or ""
    if summary:
        return f"{label} ({summary}):\n{body}"
    return f"{label}:\n{body}"
