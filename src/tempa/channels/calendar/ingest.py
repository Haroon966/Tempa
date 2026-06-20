from __future__ import annotations

from typing import Any

from tempa.channels.calendar.client import CalendarEvent
from tempa.rag.ingest import ingest_text


def extract_participants(raw: dict[str, Any]) -> list[str]:
    participants: list[str] = []
    for att in raw.get("attendees") or []:
        if isinstance(att, dict):
            email = att.get("email")
            if email:
                participants.append(str(email))
    organizer = raw.get("organizer")
    if isinstance(organizer, dict) and organizer.get("email"):
        participants.append(str(organizer["email"]))
    return sorted(set(participants))


def ingest_calendar_event(ev: CalendarEvent) -> None:
    """FR-CAL-06: per-event unified DB ingest with meet_link + participants."""
    participants = extract_participants(ev.raw if isinstance(ev.raw, dict) else {})
    text = f"{ev.summary} — {ev.start.isoformat()} to {ev.end.isoformat()}"
    if ev.meet_url:
        text += f" — Meet: {ev.meet_url}"
    ingest_text(
        text,
        tool="calendar",
        source=ev.id,
        participants=participants,
        meet_link=ev.meet_url,
        title=ev.summary,
        tags=["event"],
    )
