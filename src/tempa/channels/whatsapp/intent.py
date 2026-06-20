from __future__ import annotations

import re
from enum import Enum
from typing import Any

_MEET_URL_RE = re.compile(r"https://meet\.google\.com/[a-z0-9\-]+", re.I)
_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")


class WhatsAppIntent(str, Enum):
    EMAIL_STATUS_FOLLOWUP = "email_status_followup"
    MEET_STATUS_FOLLOWUP = "meet_status_followup"
    ACTION_STATUS_FOLLOWUP = "action_status_followup"
    GMAIL = "gmail"
    CALENDAR = "calendar"
    MEET_JOIN = "meet_join"
    PC_TASK = "pc_task"
    COORDINATOR = "coordinator"
    CHAT = "chat"


_GMAIL_HINTS = ("gmail", "inbox")
_PC_HINTS = (
    "open vscode",
    "open code",
    "close app",
    "run shell",
    "create file",
    "write file",
    "read file",
)
_STATUS_FOLLOWUPS = {
    "why",
    "reason",
    "what happened",
    "what went wrong",
    "explain",
    "how come",
    "why not",
    "what was the reason",
}
_RESEND_HINTS = ("any more", "resend", "send again", "try again", "repeat")


def _is_calendar_task(text: str) -> bool:
    from tempa.channels.calendar.events import (
        wants_add_guest,
        wants_create_event,
        wants_delete_event,
        wants_send_calendar_invite,
    )

    lower = text.lower()
    if wants_create_event(text) or wants_delete_event(text):
        return True
    if wants_send_calendar_invite(text) or wants_add_guest(text):
        return True
    if _EMAIL_RE.search(text) and re.search(r"\b(?:send|email)\s+(?:an?\s+)?invite\b", lower):
        return True
    if re.search(r"\binvite\b", lower) and _EMAIL_RE.search(text):
        return True
    if any(k in lower for k in ("calendar", "calender")):
        if any(k in lower for k in ("meeting", "event", "invite", "guest", "schedule")):
            return True
    if re.search(r"\bsend\b.*\binvite\b", lower) and "meeting" in lower:
        return True
    return False


def _is_email_task(text: str) -> bool:
    if _is_calendar_task(text):
        return False
    lower = text.lower()
    if any(h in lower for h in _GMAIL_HINTS):
        return True
    if "@" in text and any(k in lower for k in ("send", "mail", "email")):
        if any(k in lower for k in ("invite", "calendar", "calender", "meeting", "guest")):
            return False
        return True
    return "mail" in lower and not any(k in lower for k in ("whatsapp", "meet", "calendar", "calender"))


def _is_send_email_task(text: str) -> bool:
    lower = text.lower()
    if not _is_email_task(text):
        return False
    return any(k in lower for k in ("send", "compose", "write", "reply", "forward", "draft"))


def _is_status_followup(text: str) -> bool:
    lower = text.lower().strip().rstrip("?").rstrip(".")
    return lower in _STATUS_FOLLOWUPS


def _is_resend_followup(text: str) -> bool:
    lower = text.lower().strip()
    return any(h in lower for h in _RESEND_HINTS)


def route_whatsapp_intent(text: str, context: dict[str, Any] | None = None) -> WhatsAppIntent:
    context = context or {}
    lower = text.lower()

    if _is_status_followup(text):
        return WhatsAppIntent.ACTION_STATUS_FOLLOWUP

    if _is_resend_followup(text):
        return WhatsAppIntent.ACTION_STATUS_FOLLOWUP

    if _MEET_URL_RE.search(text) or (lower.startswith("join ") and "meet.google.com" in lower):
        return WhatsAppIntent.MEET_JOIN

    if _is_calendar_task(text):
        return WhatsAppIntent.CALENDAR

    if _is_email_task(text) or _is_send_email_task(text):
        return WhatsAppIntent.GMAIL

    if any(hint in lower for hint in _PC_HINTS):
        return WhatsAppIntent.COORDINATOR

    if context.get("meet_url"):
        return WhatsAppIntent.MEET_JOIN

    return WhatsAppIntent.CHAT
