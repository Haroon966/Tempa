from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from tempa.channels.calendar.sync import load_calendar_snapshot
from tempa.core.text import truncate
from tempa.core.timezone import local_tz

logger = logging.getLogger(__name__)


def _parse_iso(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except Exception:
        return None


def _meetings_by_calendar_id() -> dict[str, dict[str, Any]]:
    try:
        from tempa.meet.archive import get_meetings_index_by_calendar_id

        return get_meetings_index_by_calendar_id()
    except Exception as exc:
        logger.warning("Failed to load meeting archive index: %s", exc)
        return {}


def _format_event_line(
    event: dict[str, Any],
    *,
    agenda_limit: int = 200,
    meeting_index: dict[str, dict[str, Any]] | None = None,
) -> str:
    start = _parse_iso(str(event.get("start", "")))
    tz = local_tz()
    time_str = start.astimezone(tz).strftime("%a %H:%M") if start else "?"
    summary = event.get("summary") or "(no title)"
    status = event.get("status") or "confirmed"
    line = f"- {time_str}: {summary}"
    if status != "confirmed":
        line += f" [{status}]"
    agenda = truncate(str(event.get("description") or ""), agenda_limit)
    if agenda:
        line += f" — Agenda: {agenda}"
    attendees = event.get("attendees") or []
    if attendees:
        line += f" — Attendees: {', '.join(attendees[:5])}"
    if event.get("meet_url"):
        line += f" — Meet: {event['meet_url']}"
    if meeting_index:
        archived = meeting_index.get(str(event.get("id", "")))
        if archived:
            tldr = archived.get("tldr") or ""
            if tldr:
                line += f" — Minutes: {truncate(tldr, 150)}"
    return line


def _fetch_live_meeting_block() -> str:
    try:
        from tempa.meet.archive import read_live_meeting_state
        from tempa.meet.service import get_active_meeting_ids

        active = get_active_meeting_ids()
        if not active:
            return ""
        meeting_id = active[0]
        state = read_live_meeting_state(meeting_id)
        lines = [f"Live meeting in progress (id: {meeting_id[:8]})"]
        tail = (state.get("transcript_tail") or "").strip()
        if tail:
            lines.append("Recent transcript:\n" + truncate(tail, 600))
        notes = (state.get("live_notes") or "").strip()
        if notes:
            lines.append("Live notes:\n" + truncate(notes, 400))
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Failed to fetch live meeting block: %s", exc)
        return ""


def build_meeting_context_pack(
    *,
    days_past: int = 14,
    days_future: int = 14,
    agenda_limit: int = 200,
) -> dict[str, Any]:
    """Structured calendar + meeting context from local snapshot + archive."""
    now = dt.datetime.now(dt.timezone.utc)
    tz = local_tz()
    today_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + dt.timedelta(days=1)

    snapshot = load_calendar_snapshot()
    events = [e for e in (snapshot.get("events") or []) if isinstance(e, dict)]
    cancelled_extra = [
        e for e in (snapshot.get("cancelled_events") or []) if isinstance(e, dict)
    ]
    meeting_index = _meetings_by_calendar_id()

    upcoming: list[dict[str, Any]] = []
    recent_past: list[dict[str, Any]] = []
    recently_canceled: list[dict[str, Any]] = []
    today_events: list[dict[str, Any]] = []

    past_cutoff = now - dt.timedelta(days=days_past)
    future_cutoff = now + dt.timedelta(days=days_future)

    for event in events:
        start = _parse_iso(str(event.get("start", "")))
        if start is None:
            continue
        status = event.get("status") or "confirmed"
        start_local = start.astimezone(tz)

        if status == "cancelled":
            if start >= past_cutoff:
                recently_canceled.append(event)
            continue

        if today_start <= start_local < today_end:
            today_events.append(event)

        if start >= now and start <= future_cutoff:
            upcoming.append(event)
        elif start < now and start >= past_cutoff:
            recent_past.append(event)

    for event in cancelled_extra:
        start = _parse_iso(str(event.get("start", "")))
        if start is None:
            continue
        if start >= past_cutoff:
            recently_canceled.append(event)

    upcoming.sort(key=lambda e: str(e.get("start", "")))
    recent_past.sort(key=lambda e: str(e.get("start", "")), reverse=True)
    recently_canceled.sort(key=lambda e: str(e.get("start", "")), reverse=True)
    today_events.sort(key=lambda e: str(e.get("start", "")))

    next_meeting = ""
    for event in upcoming:
        start = _parse_iso(str(event.get("start", "")))
        if start and start >= now:
            next_meeting = _format_event_line(event, agenda_limit=120, meeting_index=meeting_index)
            break

    today_lines = [
        _format_event_line(e, agenda_limit=120, meeting_index=meeting_index) for e in today_events[:8]
    ]
    today_summary = f"Today ({len(today_events)} event{'s' if len(today_events) != 1 else ''})"
    if next_meeting:
        today_summary += f"\nNext up: {next_meeting.lstrip('- ')}"
    if today_lines:
        today_summary += "\n" + "\n".join(today_lines)

    pack: dict[str, Any] = {
        "today_summary": today_summary,
        "upcoming": upcoming[:20],
        "recent_past": recent_past[:15],
        "recently_canceled": recently_canceled[:10],
        "live_meeting": _fetch_live_meeting_block(),
        "last_sync_at": snapshot.get("last_sync_at") or "",
    }
    return pack


def format_meeting_context_for_prompt(pack: dict[str, Any], *, full: bool = False) -> str:
    """Format context pack as prompt text."""
    meeting_index = _meetings_by_calendar_id()
    agenda_limit = 500 if full else 200
    parts: list[str] = []

    last_sync = pack.get("last_sync_at") or ""
    if last_sync:
        parts.append(f"Calendar snapshot (as of {last_sync})")

    today = pack.get("today_summary") or ""
    if today:
        parts.append(f"Calendar today:\n{today}")

    if full:
        upcoming = pack.get("upcoming") or []
        if upcoming:
            lines = [
                _format_event_line(e, agenda_limit=agenda_limit, meeting_index=meeting_index)
                for e in upcoming
            ]
            parts.append("Upcoming calendar:\n" + "\n".join(lines))

        recent_past = pack.get("recent_past") or []
        if recent_past:
            lines = []
            for e in recent_past:
                line = _format_event_line(e, agenda_limit=agenda_limit, meeting_index=meeting_index)
                event_id = str(e.get("id", ""))
                if event_id not in meeting_index:
                    line += " — (no minutes captured)"
                lines.append(line)
            parts.append("Recent past meetings:\n" + "\n".join(lines))

        canceled = pack.get("recently_canceled") or []
        if canceled:
            lines = []
            for e in canceled:
                start = _parse_iso(str(e.get("start", "")))
                tz = local_tz()
                when = start.astimezone(tz).strftime("%a %H:%M") if start else "?"
                lines.append(f"- {when}: {e.get('summary', '?')} [cancelled]")
            parts.append("Recently canceled:\n" + "\n".join(lines))

    live = pack.get("live_meeting") or ""
    if live:
        parts.append(f"Live meeting:\n{live}")

    return "\n\n".join(parts) if parts else ""
