"""Keyword fallback classifier for #presence posts (full taxonomy)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tempa.settings import get_settings

STATUSES = (
    "leave",
    "half_day",
    "leave_early",
    "remote",
    "late",
    "partial_away",
    "ooo",
    "back",
    "office",
    "field_visit",
    "travel",
    "limited",
    "other",
)

LOCATIONS = ("i10", "niete", "h9", "rawalpindi", "moawin_hq", "other_site")
REASONS = ("sick", "family", "appointment", "hospital", "power", "internet", "commute")

# Priority order for rules (first match wins)
_STATUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "leave",
        re.compile(
            r"\b("
            r"on leave|on a leave|taking leave|sick leave|medical leave|"
            r"taking (the )?day off|taking an off|taking today off|taking tomorrow off|"
            r"take tomorrow off|day off|out sick|won'?t be able to come|"
            r"taking (the )?day off|on medical leave"
            r")\b",
            re.I,
        ),
    ),
    (
        "half_day",
        re.compile(r"\b(half[- ]?day|short leave|rest of the day off)\b", re.I),
    ),
    (
        "leave_early",
        re.compile(
            r"\b("
            r"leav(e|ing) (a bit |a little |a little bit )?early|"
            r"signing off|logging off|left early|going home early|"
            r"leaving office early"
            r")\b",
            re.I,
        ),
    ),
    (
        "field_visit",
        re.compile(
            r"\b("
            r"school visits?|schools? visit|on school|"
            r"moawin[- ]?h[oq]|movain[- ]?h[oq]|"
            r"job fair|pef ho|sed\b|aeo.?s? training|"
            r"visiting rwp|rawalpindi office for|"
            r"on (a )?visit|off to moawin|at moawin"
            r")\b",
            re.I,
        ),
    ),
    (
        "travel",
        re.compile(
            r"\b(en route|on (the )?way|travell?ing|heading to|going to)\b",
            re.I,
        ),
    ),
    (
        "remote",
        re.compile(
            r"\b("
            r"working remotely|work(ing)? remotely|working remote|"
            r"remotely available|available remotely|"
            r"work(ing)? from home|wfh|from home|continue remotely"
            r")\b",
            re.I,
        ),
    ),
    (
        "late",
        re.compile(
            r"\b("
            r"running (a bit )?late|a bit late|will be (a bit )?late|"
            r"will join|join(ing)? (after|around|in)|"
            r"reach(ing)? (work|office)|in (the )?office around|"
            r"will be in (the )?office around"
            r")\b",
            re.I,
        ),
    ),
    (
        "partial_away",
        re.compile(
            r"\b("
            r"away in (1st|first) half|first half|2nd half|second half|"
            r"available (after|post)|won'?t be available|"
            r"will not be available|not available (after|in)|"
            r"joining in 2nd|join(ing)? in (the )?(2nd|second)"
            r")\b",
            re.I,
        ),
    ),
    (
        "ooo",
        re.compile(
            r"\b("
            r"ooo|out of office|out for lunch|stepping out|"
            r"away from the system|i'?ll be out|for \d+\s*(mins?|minutes|hours?)"
            r")\b",
            re.I,
        ),
    ),
    (
        "limited",
        re.compile(
            r"\b("
            r"limited availability|internet (instability|issue)|"
            r"no electricity|power outage|ups is dead"
            r")\b",
            re.I,
        ),
    ),
    ("back", re.compile(r"\b(back to office|back in)\b", re.I)),
    (
        "office",
        re.compile(
            r"\b(in office|in the office|on[- ]site|at (the )?office|join office|working from)\b",
            re.I,
        ),
    ),
]

_LOCATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("i10", re.compile(r"\bi[- ]?10\b", re.I)),
    ("niete", re.compile(r"\bniete\b", re.I)),
    ("h9", re.compile(r"\bh[/ -]?9\b", re.I)),
    ("rawalpindi", re.compile(r"\b(rawalpindi|rwp)\b", re.I)),
    ("moawin_hq", re.compile(r"\b(moawin|movain)[- ]?h[oq]\b", re.I)),
]

_REASON_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sick", re.compile(r"\b(not feeling well|unwell|fever|diarrhea|headache|body aches|sore throat|infection|out sick|sick)\b", re.I)),
    ("hospital", re.compile(r"\bhospital\b", re.I)),
    ("appointment", re.compile(r"\b(doctor|appointment|medical check|ptm)\b", re.I)),
    ("family", re.compile(r"\b(family|son|sister|take care of)\b", re.I)),
    ("power", re.compile(r"\b(power outage|no electricity|ups)\b", re.I)),
    ("internet", re.compile(r"\binternet\b", re.I)),
    ("commute", re.compile(r"\b(commute|traffic)\b", re.I)),
]

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>|<#[A-Z0-9]+(?:\|[^>]*)?>|<!subteam\^[^>]+>")
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def strip_slack_markup(text: str) -> str:
    cleaned = _MENTION_RE.sub("", text or "")
    cleaned = cleaned.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", cleaned).strip()


def presence_tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tempa_timezone or "Asia/Karachi")
    except Exception:
        return ZoneInfo("Asia/Karachi")


def today_in_tz(now: datetime | None = None) -> date:
    tz = presence_tz()
    current = now.astimezone(tz) if now else datetime.now(tz)
    return current.date()


def _detect_location(text: str) -> tuple[str | None, str | None]:
    for loc, pat in _LOCATION_PATTERNS:
        m = pat.search(text)
        if m:
            return loc, m.group(0)
    # other known sites without enum alias
    if re.search(r"\b(g7/?2|lahore|pef|sed)\b", text, re.I):
        m = re.search(r"\b(g7/?2|lahore|pef|sed)\b", text, re.I)
        return "other_site", m.group(0) if m else None
    return None, None


def _detect_reason(text: str) -> str | None:
    for reason, pat in _REASON_PATTERNS:
        if pat.search(text):
            return reason
    return None


def _detect_half(text: str) -> str | None:
    tl = text.lower()
    if re.search(r"\b(1st|first) half\b", tl):
        return "first"
    if re.search(r"\b(2nd|second) half\b", tl):
        return "second"
    return None


def _parse_when(text: str, *, base: date) -> tuple[str, date, date | None]:
    tl = text.lower()
    if re.search(r"\btomorrow\b", tl):
        d = base + timedelta(days=1)
        return "tomorrow", d, d
    m = re.search(r"\btill\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", tl)
    if m:
        target = _WEEKDAYS[m.group(1)]
        days_ahead = (target - base.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        end = base + timedelta(days=days_ahead)
        return "range", base, end
    m = re.search(r"\bnext\s+(\d+)\s+days?\b", tl)
    if m:
        n = int(m.group(1))
        end = base + timedelta(days=max(0, n - 1))
        return "range", base, end
    m = re.search(r"\b(today\s*[&and]+\s*tomorrow|today\s*&\s*tomorrow)\b", tl)
    if m:
        return "range", base, base + timedelta(days=1)
    return "today", base, base


def classify_presence_text(
    text: str,
    *,
    base_date: date | None = None,
    message_ts: str = "",
) -> dict[str, Any]:
    """Classify freeform presence text with keyword rules."""
    cleaned = strip_slack_markup(text)
    base = base_date or today_in_tz()
    if message_ts:
        try:
            ts_f = float(message_ts)
            base = datetime.fromtimestamp(ts_f, tz=presence_tz()).date()
        except (TypeError, ValueError, OSError):
            pass

    status = "other"
    for name, pat in _STATUS_PATTERNS:
        if pat.search(cleaned):
            status = name
            break

    # office + named site: keep office or remote as-is; location separate
    if status == "office" and re.search(r"\bworking from\b", cleaned, re.I):
        # "Working from I10" is office-at-site; "Working from home" already caught as remote
        if re.search(r"\bfrom home\b", cleaned, re.I):
            status = "remote"

    location, location_raw = _detect_location(cleaned)
    # Working from H9 / I10 without other status → office
    if status == "other" and location:
        status = "office"

    reason = _detect_reason(cleaned)
    half = _detect_half(cleaned)
    when, start, end = _parse_when(cleaned, base=base)
    note = cleaned[:120] if cleaned else ""

    return {
        "status": status,
        "location": location,
        "location_raw": location_raw,
        "reason": reason,
        "when": when,
        "when_start": start.isoformat(),
        "when_end": (end or start).isoformat(),
        "half": half,
        "note": note,
        "raw_text": cleaned,
        "source": "rules",
    }


def dates_for_classification(result: dict[str, Any]) -> list[str]:
    start = date.fromisoformat(str(result["when_start"]))
    end = date.fromisoformat(str(result.get("when_end") or result["when_start"]))
    if end < start:
        end = start
    # ponytail: cap multi-day expansion at 14 days
    days: list[str] = []
    cur = start
    for _ in range(14):
        days.append(cur.isoformat())
        if cur >= end:
            break
        cur += timedelta(days=1)
    return days
