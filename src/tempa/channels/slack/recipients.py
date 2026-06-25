from __future__ import annotations

import logging
import re
from typing import Any

from tempa.channels.contacts.store import search_contacts
from tempa.channels.gmail.recipients import _name_match_score
from tempa.channels.slack.client import list_users, load_slack_client, user_display_name

logger = logging.getLogger(__name__)

_READ_MESSAGE_RE = re.compile(
    r"\b(?:check|read|show|get|what(?:'s| is)|tell me|latest|last)\b.*\bmessage\b",
    re.I,
)

_SEND_TO_PATTERNS = (
    re.compile(
        r"send(?:\s+a)?\s+message\s+to\s+(.+?)(?:\s+(?:saying|with|that)\b|\s*$)",
        re.I,
    ),
    re.compile(r"send\s+(.+?)\s+a\s+message(?:\s+(?:saying|with)\b|\s*$)", re.I),
    re.compile(r"\bmessage\s+to\s+(.+?)(?:\s+(?:saying|with|on\s+slack)\b|\s*$)", re.I),
    re.compile(r"\bdm\s+(.+?)(?:\s+(?:saying|with)\b|\s*$)", re.I),
    re.compile(r"ping\s+(.+?)(?:\s+(?:saying|with)\b|\s*$)", re.I),
)


def wants_slack_send_intent(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if _READ_MESSAGE_RE.search(cleaned):
        return False
    if re.search(r"\bmessage\s+(?:from|of|in)\b", cleaned, re.I):
        return False
    if re.search(r"\b(?:send|dm|ping)\b", cleaned, re.I):
        return True
    return bool(re.search(r"\bmessage\s+to\b", cleaned, re.I))

_BODY_PATTERNS = (
    re.compile(r"\bsaying\s+(.+)$", re.I),
    re.compile(r"\bwith\s+(?:message|text)\s+(.+)$", re.I),
    re.compile(r"\bmessage\s*[:\-]\s*(.+)$", re.I),
)


def extract_slack_recipient_name(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for pattern in _SEND_TO_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        name = match.group(1).strip(" .,\"'")
        if not name:
            continue
        lower = name.lower()
        if lower in {"slack", "them", "him", "her", "user"}:
            continue
        return name
    return ""


def extract_slack_message_body(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for pattern in _BODY_PATTERNS:
        match = pattern.search(text)
        if match:
            body = match.group(1).strip(" .,\"'")
            if body:
                return body
    return ""


def _user_id_from_contact(contact: dict[str, Any]) -> str:
    cid = str(contact.get("id") or "")
    if cid.startswith("slack:"):
        return cid.split(":", 1)[1]
    return ""


def _resolve_from_users_api(query: str) -> dict[str, str]:
    client = load_slack_client()
    if client is None:
        return {}
    try:
        users = list_users(client)
    except Exception:
        logger.exception("Slack users.list failed during recipient resolve")
        return {}

    best_score = 0
    best: dict[str, str] = {}
    for user in users:
        if user.get("deleted") or user.get("is_bot"):
            continue
        uid = str(user.get("id") or "")
        if not uid:
            continue
        name = user_display_name(user)
        score = max(_name_match_score(query, name), _name_match_score(query, user.get("name", "")))
        if score > best_score:
            best_score = score
            best = {"user_id": uid, "name": name}
    return best if best_score >= 70 else {}


def resolve_slack_recipient(query: str) -> dict[str, str]:
    query = query.strip()
    if not query:
        return {}

    if query.startswith("U") and len(query) >= 9:
        return {"user_id": query, "name": query}
    if query.startswith("D") and len(query) >= 9:
        return {"channel_id": query, "name": query}

    for hit in search_contacts(query, limit=10):
        if hit.get("source") != "slack":
            continue
        uid = _user_id_from_contact(hit)
        if uid:
            return {"user_id": uid, "name": str(hit.get("name") or query)}

    for hit in search_contacts(query, limit=5):
        uid = _user_id_from_contact(hit)
        if uid:
            return {"user_id": uid, "name": str(hit.get("name") or query)}
        score = _name_match_score(query, str(hit.get("name") or ""))
        if score >= 70 and hit.get("name"):
            api = _resolve_from_users_api(str(hit["name"]))
            if api.get("user_id"):
                return api

    return _resolve_from_users_api(query)
