"""Classify Meet participants as humans vs known meeting bots."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Seed list — also mirrored in config/meet_bots.yaml for easy extension.
_DEFAULT_BOT_SUBSTRINGS: tuple[str, ...] = (
    "notetaker",
    "note taker",
    "meeting notes",
    "gemini",
    "rumi",
    "otter",
    "fireflies",
    "read.ai",
    "read ai",
    "granola",
    "fathom",
    "tl;dv",
    "tldv",
    "krisp",
    "equal time",
    "chorus",
    "gong",
    "avoma",
    "fellow",
    "scribe",
    "tactiq",
    "supernormal",
    "nyota",
    "meetgeek",
    "meeto",
    "automation",
    "recorder",
    "tempa",
)


def _config_path() -> Path:
    from tempa.settings import get_settings

    return get_settings().config_dir / "meet_bots.yaml"


@lru_cache(maxsize=1)
def bot_name_substrings() -> tuple[str, ...]:
    """Return configured bot name substrings (defaults + YAML overrides merged)."""
    names = list(_DEFAULT_BOT_SUBSTRINGS)
    path = _config_path()
    if path.exists():
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            extra = data.get("bot_name_substrings") or []
            if isinstance(extra, list):
                for item in extra:
                    s = str(item or "").strip().lower()
                    if s and s not in names:
                        names.append(s)
        except Exception:
            logger.warning("Failed to load meet_bots.yaml from %s", path, exc_info=True)
    return tuple(names)


def bot_name_regex() -> re.Pattern[str]:
    """JS/Python-friendly alternation of bot substrings (escaped)."""
    parts = [re.escape(s) for s in bot_name_substrings() if s]
    if not parts:
        return re.compile(r"a^")  # never matches
    return re.compile("|".join(parts), re.IGNORECASE)


def is_meeting_bot(name: str | None) -> bool:
    """True when display name matches a known meeting-bot / note-taker pattern."""
    cleaned = (name or "").strip()
    if not cleaned:
        return False
    return bool(bot_name_regex().search(cleaned))


def count_humans(names: list[str] | tuple[str, ...]) -> int:
    """Count participants that are not known meeting bots.

    Empty/unknown names count as human (safer: stay in the call).
    """
    humans = 0
    for name in names:
        if is_meeting_bot(name):
            continue
        humans += 1
    return humans


def clear_bot_cache() -> None:
    bot_name_substrings.cache_clear()
