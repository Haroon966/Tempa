from __future__ import annotations

import re
from dataclasses import dataclass, field

_CREATE_RE = re.compile(
    r"\b("
    r"create\s+(a\s+)?(jira\s+)?ticket|"
    r"log\s+(a\s+)?ticket|"
    r"raise\s+(a\s+)?(jira\s+)?(ticket|issue)|"
    r"assign\s+(me\s+)?(a\s+)?(jira\s+)?ticket|"
    r"asign\s+(me\s+)?(a\s+)?ticket|"
    r"assign\s+ticket\s+to|"
    r"new\s+jira\s+(ticket|issue)|"
    r"open\s+(a\s+)?(jira\s+)?(ticket|issue)"
    r")\b",
    re.I,
)

_EDIT_RE = re.compile(
    r"\b("
    r"change\s+assignee|"
    r"update\s+summary|"
    r"edit\s+(the\s+)?(ticket|issue|summary)|"
    r"re-?assign|"
    r"never\s+mind|"
    r"cancel(\s+ticket|\s+this|\s+draft)?|"
    r"add\s+comment"
    r")\b",
    re.I,
)

_CONFIRM_RE = re.compile(
    r"^\s*(yes|yep|yeah|y|go|create\s+it|lgtm|confirm|looks\s+good|ship\s+it)\s*[!.]*\s*$",
    re.I,
)

_SELF_ASSIGN_RE = re.compile(
    r"\bassign\s+(it\s+)?to\s+me\b|\bassign\s+me\b|\basign\s+me\b|\bmy\s+ticket\b",
    re.I,
)
_READ_RE = re.compile(
    r"\b(list|show|find|search|get|fetch|pull|lookup|look\s+up|what|which)\b.*\b(jira\s+)?(tickets?|issues?)\b"
    r"|\b(jira\s+)?(tickets?|issues?)\b.*\b(for\s+me|assigned|mine|in\s+progress)\b",
    re.I,
)
_ASSIGNEE_RE = re.compile(
    r"\b(?:assign(?:ed)?\s+(?:to|for)|for)\s+([A-Za-z][\w.\- ]{1,40})",
    re.I,
)
_URGENT_RE = re.compile(r"\b(urgent|asap|critical|p0|p1|high\s+priority|blocker)\b", re.I)
_PROJECT_RE = re.compile(r"\b(?:project|in)\s+([A-Z][A-Z0-9]{1,15})\b")
_EMAIL_IN_TEXT = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")


@dataclass
class TicketFields:
    summary: str = ""
    description: str = ""
    assignee_hint: str = ""
    self_assign: bool = False
    project: str = ""
    priority: str = ""
    labels: list[str] = field(default_factory=list)
    component_hints: list[str] = field(default_factory=list)


def wants_jira_ticket_create(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _READ_RE.search(t):
        return False
    if _CREATE_RE.search(t):
        return True
    lower = t.lower()
    if "jira" in lower and any(k in lower for k in ("ticket", "issue", "assign")):
        return True
    if _SELF_ASSIGN_RE.search(t) and any(k in lower for k in ("ticket", "issue", "bug", "task")):
        return True
    return False


def wants_jira_ticket_edit(text: str) -> bool:
    return bool(_EDIT_RE.search(text or ""))


def is_ticket_confirm(text: str) -> bool:
    return bool(_CONFIRM_RE.match(text or ""))


def is_ticket_cancel(text: str) -> bool:
    lower = (text or "").lower()
    return any(p in lower for p in ("never mind", "cancel", "abort", "stop"))


def parse_ticket_request(text: str) -> TicketFields:
    t = (text or "").strip()
    fields = TicketFields()
    fields.self_assign = bool(_SELF_ASSIGN_RE.search(t))

    m = _ASSIGNEE_RE.search(t)
    if m and not fields.self_assign:
        hint = m.group(1).strip().rstrip(".,!?")
        hint = re.split(r"\s+for\s+", hint, maxsplit=1, flags=re.I)[0].strip()
        fields.assignee_hint = hint

    for_m = re.search(
        r"\bfor\s+(.+?)(?:\s+in\s+[A-Z][A-Z0-9]{1,15}\b|\s+(?:urgent|asap)\b|\s*$)",
        t,
        re.I,
    )
    if for_m:
        fields.summary = for_m.group(1).strip(" .,-")[:200]

    m = _PROJECT_RE.search(t)
    if m:
        fields.project = m.group(1).upper()

    if _URGENT_RE.search(t):
        fields.priority = "High"

    email = _EMAIL_IN_TEXT.search(t)
    if email and not fields.assignee_hint:
        fields.assignee_hint = email.group(0)

    summary = t
    for pattern in (_CREATE_RE, _ASSIGNEE_RE, _PROJECT_RE, _SELF_ASSIGN_RE):
        summary = pattern.sub("", summary)
    summary = re.sub(r"\s+", " ", summary).strip(" .,-")
    for prefix in ("please", "can you", "could you", "i need", "we need"):
        if summary.lower().startswith(prefix):
            summary = summary[len(prefix) :].strip()
    if len(summary) > 8:
        fields.summary = summary[:200]
    return fields
