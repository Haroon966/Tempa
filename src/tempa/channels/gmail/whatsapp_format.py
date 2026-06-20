from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from typing import Any

from tempa.channels.gmail.query import format_query_label, is_generic_inbox_query

_NOISE_SENDERS = (
    "notifications@github.com",
    "noreply@",
    "no-reply@",
    "mailer-daemon@",
)


def _sender_display(from_header: str) -> str:
    if not from_header:
        return "Unknown"
    match = re.match(r"^([^<]+)<", from_header)
    if match:
        name = match.group(1).strip().strip('"')
        if name:
            return name
    if "@" in from_header:
        return from_header.split("@")[0]
    return from_header


def _sender_email(from_header: str) -> str:
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).strip()
    return from_header.strip()


def _short_date(date_header: str) -> str:
    if not date_header:
        return ""
    try:
        dt = parsedate_to_datetime(date_header)
        return dt.strftime("%b %-d") if dt else ""
    except Exception:
        return date_header[:12]


def _is_noise(msg: dict[str, Any], query: str) -> bool:
    if not is_generic_inbox_query(query):
        return False
    sender = _sender_email(str(msg.get("from", ""))).lower()
    return any(pattern in sender for pattern in _NOISE_SENDERS)


def format_whatsapp_email_list(payload: dict[str, Any], *, max_items: int = 5) -> str:
    """Compact WhatsApp-friendly email list (fluxi-style structured reply)."""
    count = int(payload.get("count") or 0)
    query = str(payload.get("query") or "")
    messages = payload.get("messages") or []

    if count == 0:
        label = format_query_label(query)
        if label:
            return f"No emails found for `{label}`."
        return "No emails found."

    filtered = [m for m in messages if isinstance(m, dict) and not _is_noise(m, query)]
    if not filtered:
        filtered = [m for m in messages if isinstance(m, dict)]

    label = format_query_label(query)
    header = f"Found {count} email(s)"
    if label:
        header += f" for `{label}`"
    if payload.get("used_fallback_query"):
        header += f" (also tried `{payload['used_fallback_query']}`)"

    lines = [header + ":"]
    for idx, msg in enumerate(filtered[:max_items], start=1):
        subject = str(msg.get("subject") or "(no subject)").strip()
        sender = _sender_display(str(msg.get("from") or ""))
        when = _short_date(str(msg.get("date") or ""))
        unread = " · unread" if msg.get("unread") else ""
        meta = f" ({sender})" if sender else ""
        date_part = f" · {when}" if when else ""
        lines.append(f"{idx}. {subject}{meta}{date_part}{unread}")
        snippet = str(msg.get("snippet") or "").strip()
        if snippet and len(snippet) > 10:
            lines.append(f"   {snippet[:120]}")

    remaining = count - min(len(filtered), max_items)
    if remaining > 0:
        lines.append(f"…and {remaining} more in Gmail.")
    return "\n".join(lines)
