"""Permanent Rumi pack routing — alias table, not phrase bandaids.

Any chat path (Slack early gate, coordinator pre-hook, grounding, RAG) must use
``classify_rumi`` so meeting archives / RAG cannot invent answers about the
vendored skills pack.
"""

from __future__ import annotations

import re
from typing import Literal

RumiRoute = Literal["capability", "agent"]

# Word-boundary aliases for the skills pack (never bare "rumi" alone — Meet bot).
_PACK_ALIASES = (
    "rumixtempa",
    "agent-skills",
    "agent skills",
)

# Tokens that make "rumi" mean the pack, not the Meet participant.
_RUMI_COMPANIONS = frozenset(
    {
        "skill",
        "skills",
        "pack",
        "agent",
        "notion",
        "board",
        "codebase",
        "shadow",
        "lesson",
        "worksheet",
        "voicenote",
        "storytime",
    }
)

_MEET_CHATTER_RE = re.compile(
    r"\brumi\b.{0,40}\b(?:left|joined|leaving|joining)\b"
    r"|\b(?:left|joined|leaving|joining)\b.{0,40}\brumi\b",
    re.I,
)

_MEET_URL_RE = re.compile(r"meet\.google\.com", re.I)

_CAPABILITY_CUES = re.compile(
    r"\b("
    r"do you have|have you|got any|what(?:'s| are| is)|which|"
    r"list|show|tell me|can you|are there|available|support"
    r")\b",
    re.I,
)

_WORK_VERBS = re.compile(
    r"\b(?:use|ask|via|with|run|create|post|query|find|build|generate|make|send|update|move|comment)\b",
    re.I,
)

_AGENT_HANDOFF = re.compile(
    r"\b(?:use|ask|via|with)\s+rumi\b"
    r"|\brumi\s+(?:do|please)\b"
    r"|^\s*rumi\s*:"
    r"|\brumixtempa\b",
    re.I,
)

_WORD = re.compile(r"[a-z0-9][a-z0-9\-']*", re.I)


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text or "")]


def _has_pack_signal(text: str) -> bool:
    lower = (text or "").lower()
    for alias in _PACK_ALIASES:
        if alias in lower:
            return True
    toks = _tokens(text)
    if "rumixtempa" in toks:
        return True
    if "rumi" not in toks:
        return False
    if re.search(r"(^|\s)rumi\s*:", text or "", re.I):
        return True
    if any(t in _RUMI_COMPANIONS for t in toks):
        return True
    if re.search(r"\b(?:use|ask|via|with|can|does|have)\s+rumi\b", lower):
        return True
    return False


def classify_rumi(user_message: str) -> RumiRoute | None:
    """Return capability | agent when this is a Rumi skills-pack ask, else None."""
    text = (user_message or "").strip()
    if not text:
        return None
    if _MEET_URL_RE.search(text):
        return None
    if _MEET_CHATTER_RE.search(text) and not re.search(r"\bskills?\b", text, re.I):
        return None
    try:
        from tempa.agents.intent import wants_calendar, wants_meeting_archive

        if (wants_calendar(text) or wants_meeting_archive(text)) and not _has_pack_signal(text):
            return None
    except Exception:
        pass
    if not _has_pack_signal(text):
        return None

    handoff = bool(_AGENT_HANDOFF.search(text))
    if handoff:
        return "agent"
    # Work verb + pack signal (e.g. "create a notion card with rumi skills")
    if _WORK_VERBS.search(text) and not _CAPABILITY_CUES.search(text):
        return "agent"
    if _CAPABILITY_CUES.search(text):
        return "capability"
    # Default: capability — safe inventory, no Cursor until they say "use rumi to…"
    return "capability"


def is_rumi_pack_route(user_message: str) -> bool:
    return classify_rumi(user_message) is not None
