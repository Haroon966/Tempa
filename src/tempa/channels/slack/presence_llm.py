"""Cheap Groq LLM classifier for #presence posts."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from tempa.channels.slack.presence_parse import (
    LOCATIONS,
    REASONS,
    STATUSES,
    classify_presence_text,
    presence_tz,
    strip_slack_markup,
    today_in_tz,
)
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_SYSTEM = """You classify Slack #presence status messages for a Pakistan office team.
Return ONLY valid JSON with these keys:
status, location, location_raw, reason, when, until_date, half, note

status (exactly one):
- leave: full day/multi-day off, sick leave, medical leave, day off, out sick
- half_day: half day or short leave
- leave_early: signing/logging off early, leaving early
- remote: WFH / working remotely
- late: running late, will join after, reach office around
- partial_away: away 1st/2nd half, available after X, not available after X
- ooo: short OOO, lunch, stepping out, away from system briefly
- back: back to office
- office: in office / on-site / working from a named office site
- field_visit: school visits, Moawin HO/HQ, PEF/SED, job fair, training visit (still working)
- travel: en route / on the way / travelling
- limited: limited availability, no electricity, internet issues
- other: greetings/noise only

location (or null): i10 | niete | h9 | rawalpindi | moawin_hq | other_site
reason (or null): sick | family | appointment | hospital | power | internet | commute
when: today | tomorrow | range
until_date: YYYY-MM-DD or null (for range/multi-day)
half: first | second | null
note: one short phrase

Priority if overlapping: leave > half_day > leave_early > field_visit > travel > remote > late > partial_away > ooo > limited > back > office > other
School visit is field_visit NOT leave. Signing off early is leave_early NOT ooo.
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _normalize_llm(
    data: dict[str, Any],
    *,
    cleaned: str,
    base: date,
) -> dict[str, Any] | None:
    status = str(data.get("status") or "other").strip().lower()
    if status not in STATUSES:
        return None

    location = data.get("location")
    if location in ("", "null", None):
        location = None
    else:
        location = str(location).strip().lower()
        if location not in LOCATIONS:
            location = "other_site" if location else None

    reason = data.get("reason")
    if reason in ("", "null", None):
        reason = None
    else:
        reason = str(reason).strip().lower()
        if reason not in REASONS:
            reason = None

    half = data.get("half")
    if half in ("", "null", None):
        half = None
    else:
        half = str(half).strip().lower()
        if half not in ("first", "second"):
            half = None

    when = str(data.get("when") or "today").strip().lower()
    if when not in ("today", "tomorrow", "range"):
        when = "today"

    start = base
    end = base
    if when == "tomorrow":
        start = end = base + timedelta(days=1)
    elif when == "range":
        until = data.get("until_date")
        try:
            end = date.fromisoformat(str(until)) if until else base
        except ValueError:
            end = base
        if end < start:
            end = start

    location_raw = data.get("location_raw")
    if location_raw in ("", "null", None):
        location_raw = None
    else:
        location_raw = str(location_raw).strip()[:80] or None

    note = str(data.get("note") or cleaned[:120]).strip()[:120]

    return {
        "status": status,
        "location": location,
        "location_raw": location_raw,
        "reason": reason,
        "when": when,
        "when_start": start.isoformat(),
        "when_end": end.isoformat(),
        "half": half,
        "note": note,
        "raw_text": cleaned,
        "source": "llm",
    }


def classify_with_llm(
    text: str,
    *,
    base_date: date | None = None,
    message_ts: str = "",
    today_date: date | None = None,
) -> dict[str, Any] | None:
    """Call cheap Groq model. Returns None on failure (caller uses rules)."""
    settings = get_settings()
    if not settings.load_groq_api_key():
        return None

    cleaned = strip_slack_markup(text)
    if not cleaned:
        return None

    base = base_date or today_in_tz()
    if message_ts:
        try:
            base = datetime.fromtimestamp(float(message_ts), tz=presence_tz()).date()
        except (TypeError, ValueError, OSError):
            pass
    today = today_date or today_in_tz()
    model = (settings.slack_presence_llm_model or "llama-3.1-8b-instant").strip()

    try:
        from tempa.router.groq_router import get_router

        router = get_router()
        response = router.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"today_date={today.isoformat()} (Asia/Karachi)\n"
                        f"message_date={base.isoformat()}\n"
                        f"message: {cleaned}"
                    ),
                },
            ],
            temperature=0,
            max_tokens=150,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        data = _extract_json(content)
        if not data:
            return None
        return _normalize_llm(data, cleaned=cleaned, base=base)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Presence LLM classify failed: %s", exc)
        return None


def classify_presence(
    text: str,
    *,
    base_date: date | None = None,
    message_ts: str = "",
) -> dict[str, Any]:
    """LLM first, keyword rules fallback."""
    llm = classify_with_llm(text, base_date=base_date, message_ts=message_ts)
    if llm:
        return llm
    return classify_presence_text(text, base_date=base_date, message_ts=message_ts)
