from __future__ import annotations

import re

_CALENDAR_HINTS = (
    "calendar",
    "schedule",
    "meeting",
    "meetings",
    "agenda",
    "what's on",
    "whats on",
    "today",
    "tomorrow",
    "next event",
    "standup",
    "stand up",
    "event",
    "canceled",
    "cancelled",
    "minutes",
)

_GMAIL_HINTS = (
    "gmail",
    "email",
    "e-mail",
    "inbox",
    "unread",
    "sent",
    "reply",
    "forward",
    "draft",
    "subject",
    "from ",
    "mail",
)

_MEETING_QA_HINTS = (
    "minutes",
    "what happened",
    "meeting summary",
    "in the meeting",
    "in meeting",
    "last meeting",
    "recent meeting",
    "give me the minutes",
    "what was discussed",
)

_REPO_QA_HINTS = (
    "ci failed",
    "ci failure",
    "test failed",
    "tests failing",
    "vulnerability",
    "security issue",
    "branch health",
    "code quality",
    "dependabot",
    "failing build",
    "qa status",
    "qa report",
)

_FOLLOW_UP_HINTS = (
    "what",
    "which",
    "when",
    "where",
    "who",
    "that",
    "it",
    "them",
)

_FOLLOW_UP_STANDALONE = frozenset({"yes", "no", "?"})


_CASUAL_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|yo|salam|aoa|assalam(?:u)?(?:\s+alaikum)?)[!.?\s]*$",
    re.I,
)


def is_casual_greeting(text: str) -> bool:
    return bool(_CASUAL_GREETING_RE.match((text or "").strip()))


def is_follow_up(text: str) -> bool:
    lower = text.lower().strip()
    if len(lower) > 80:
        return False
    if lower in _FOLLOW_UP_STANDALONE:
        return False
    if any(h in lower for h in _FOLLOW_UP_HINTS):
        return True
    if "?" in lower and len(lower) > 3:
        return True
    return False


def wants_calendar_full(user_message: str, *, include_calendar: bool = False) -> bool:
    lower = user_message.lower()
    if include_calendar:
        return True
    if any(h in lower for h in _CALENDAR_HINTS):
        return True
    if is_follow_up(user_message) and any(
        k in lower for k in ("meeting", "event", "calendar", "agenda")
    ):
        return True
    return False


def wants_gmail_full(user_message: str) -> bool:
    lower = user_message.lower()
    if re.search(r"\b(gmail|email|e-mail|inbox)\b", lower):
        return True
    if any(h in lower for h in _GMAIL_HINTS if h not in {"mail"}):
        return True
    if re.search(r"\bmail\b", lower) and "message" not in lower:
        return True
    if is_follow_up(user_message) and any(k in lower for k in ("email", "mail", "inbox", "reply")):
        return True
    if any(h in lower for h in ("that email", "the email", "you said", "earlier")):
        return True
    return False


def wants_meeting_archive(user_message: str) -> bool:
    lower = user_message.lower()
    return any(h in lower for h in _MEETING_QA_HINTS)


def wants_repo_qa(user_message: str) -> bool:
    lower = user_message.lower()
    return any(h in lower for h in _REPO_QA_HINTS)


def wants_calendar(user_message: str) -> bool:
    lower = user_message.lower()
    return any(
        k in lower
        for k in (
            "calendar",
            "schedule",
            "meeting",
            "meetings",
            "agenda",
            "what's on",
            "whats on",
            "today",
            "tomorrow",
            "next event",
            "standup",
            "stand up",
            "event",
        )
    )


_PRIVATE_INTEGRATION_HINTS = (
    "whatsapp",
    "meet.google.com",
    "google meet",
    "join meet",
    "inbox",
    "unread email",
    "send email",
    "compose email",
    "my email",
    "my emails",
    "my calendar",
    "my inbox",
    "my meetings",
    "my mail",
)


def wants_private_integrations(user_message: str) -> bool:
    lower = user_message.lower()
    if wants_gmail_full(user_message):
        return True
    if wants_calendar(user_message):
        return True
    if wants_meeting_archive(user_message):
        return True
    if any(h in lower for h in _PRIVATE_INTEGRATION_HINTS):
        return True
    if "whatsapp" in lower or ("message" in lower and "slack" not in lower and "send" in lower):
        if any(k in lower for k in ("whatsapp", "wa ", "text me", "notify")):
            return True
    return False
