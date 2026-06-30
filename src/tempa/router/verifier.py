from __future__ import annotations

import logging
import re
from typing import Any

from tempa.agents.grounding import deterministic_reply_from_actions
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)

_EMAIL_SENT_RE = re.compile(
    r"\b(email|mail)\s+(was\s+)?sent\b|\bsent\s+(the\s+)?(email|mail)\b|\bi\s+sent\b",
    re.I,
)
_INVITE_SENT_RE = re.compile(
    r"\b(invite|invitation)\s+(was\s+)?sent\b|\bsent\s+(the\s+)?(invite|invitation)\b",
    re.I,
)
_MEET_JOINED_RE = re.compile(
    r"\b(joined|joining)\s+(the\s+)?(meet|meeting|call)\b|\bmeet\s+(is\s+)?join",
    re.I,
)
_CREATED_RE = re.compile(
    r"\b(created|scheduled)\s+(the\s+)?(event|meeting|calendar)\b",
    re.I,
)
_UNREAD_CLAIM_RE = re.compile(
    r"\b(\d+)\s+unread\b|\bno\s+unread\b|\bzero\s+unread\b|\bnothing\s+unread\b",
    re.I,
)

_SUCCESS_MARKERS = (
    "created calendar event",
    "deleted from calendar",
    "sent calendar invite",
    "joining google meet",
    "tempa is joining the meet",
)


def _action_text(pack: dict[str, Any]) -> str:
    facts = pack.get("action_facts") or []
    return "\n".join(str(f) for f in facts).lower()


def _has_confirmed_success(actions: str) -> bool:
    return any(marker in actions for marker in _SUCCESS_MARKERS)


def _extract_unread_from_gmail(pack: dict[str, Any]) -> int | None:
    for key in ("gmail_full", "gmail_compact"):
        block = str(pack.get(key) or "")
        match = re.search(r"Inbox:\s*(\d+)\s+unread", block, re.I)
        if match:
            return int(match.group(1))
    return None


def _claims_false_unread(reply: str, pack: dict[str, Any]) -> bool:
    expected = _extract_unread_from_gmail(pack)
    if expected is None:
        return False
    lower = reply.lower()
    if "no unread" in lower or "zero unread" in lower or "nothing unread" in lower:
        return expected > 0
    match = _UNREAD_CLAIM_RE.search(reply)
    if match and match.group(1):
        claimed = int(match.group(1))
        return claimed != expected
    return False


def _claims_false_action(reply: str, pack: dict[str, Any]) -> bool:
    lower_reply = reply.lower()
    actions = _action_text(pack)
    has_success = _has_confirmed_success(actions)

    if _EMAIL_SENT_RE.search(reply):
        if "sent" not in actions and "status=sent" not in actions:
            if "pending" in actions or "status=pending" in actions or not actions:
                return True

    if _INVITE_SENT_RE.search(reply):
        if "calendar invite sent" in actions or "sent calendar invite" in actions:
            return False
        if "invite" not in actions and "invited" not in actions and "attendees" not in actions:
            if not actions or "no guests" in lower_reply:
                return False
            return True

    if _MEET_JOINED_RE.search(reply):
        if has_success and ("queued" in actions or "joining google meet" in actions):
            return False
        if "failed" in actions or "status=failed" in actions or "could not join meet" in actions:
            return True
        if not actions and "queued" not in lower_reply:
            return True

    if _CREATED_RE.search(reply):
        if has_success:
            return False
        if actions and ("could not create" in actions or "calendar action failed" in actions):
            return True
        if not actions:
            return True

    if _claims_false_unread(reply, pack):
        return True

    return False


def _deterministic_correction(pack: dict[str, Any]) -> str | None:
    corrected = deterministic_reply_from_actions(pack)
    if corrected:
        return corrected
    expected_unread = _extract_unread_from_gmail(pack)
    if expected_unread is not None:
        return f"Your inbox snapshot shows {expected_unread} unread message(s)."
    calendar = pack.get("calendar_today") or pack.get("calendar_full") or ""
    if calendar.strip():
        return calendar.strip()[:800]
    gmail = pack.get("gmail_compact") or pack.get("gmail_full") or ""
    if gmail.strip() and "not connected" not in gmail:
        return gmail.strip()[:800]
    return None


def verify_reply(reply: str, grounding_pack: dict[str, Any]) -> tuple[bool, str]:
    """Check reply against grounding facts; return corrected reply on failure."""
    if not reply.strip():
        corrected = _deterministic_correction(grounding_pack)
        if corrected:
            return False, corrected
        return False, "I couldn't verify that action — please try again."

    if not _claims_false_action(reply, grounding_pack):
        return True, reply

    corrected = _deterministic_correction(grounding_pack)
    if corrected:
        return False, corrected

    try:
        router = get_router()
        facts_parts = [_action_text(grounding_pack) or "none"]
        for key in ("gmail_compact", "calendar_today", "pending_actions"):
            val = grounding_pack.get(key)
            if val:
                facts_parts.append(f"{key}:\n{val}")
        prompt = (
            "You verify assistant replies against known facts. "
            "If the reply falsely claims an email was sent, calendar invite sent, "
            "meeting joined, event created, or wrong unread count without supporting facts, "
            "rewrite it to be accurate using the grounding blocks. "
            "If facts are empty, say the action was not confirmed.\n\n"
            f"Known facts:\n" + "\n\n".join(facts_parts) + "\n\n"
            f"Reply to verify:\n{reply}"
        )
        response = router.chat_completion(
            category="text",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0,
        )
        rewritten = (response.choices[0].message.content or "").strip()
        if rewritten:
            return False, rewritten
    except Exception as exc:
        logger.warning("Verifier LLM fallback failed: %s", exc)

    return False, "I couldn't confirm that action completed — check Tempa for status."
