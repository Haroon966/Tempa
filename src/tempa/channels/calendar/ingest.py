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


def _event_description(raw: dict[str, Any], *, max_len: int = 500) -> str:
    desc = raw.get("description")
    if not isinstance(desc, str):
        return ""
    text = desc.strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _event_status(raw: dict[str, Any]) -> str:
    return str(raw.get("status") or "confirmed")


def ingest_calendar_event(ev: CalendarEvent) -> None:
    """FR-CAL-06: per-event unified DB ingest with meet_link, participants, agenda."""
    raw = ev.raw if isinstance(ev.raw, dict) else {}
    participants = extract_participants(raw)
    status = _event_status(raw)
    text = f"{ev.summary} — {ev.start.isoformat()} to {ev.end.isoformat()}"
    if status != "confirmed":
        text += f" — Status: {status}"
    agenda = _event_description(raw)
    if agenda:
        text += f" — Agenda: {agenda}"
    if participants:
        text += f" — Attendees: {', '.join(participants[:12])}"
    if ev.meet_url:
        text += f" — Meet: {ev.meet_url}"
    location = raw.get("location")
    if isinstance(location, str) and location.strip():
        text += f" — Location: {location.strip()[:200]}"
    tags = ["event"]
    if status == "cancelled":
        tags.append("cancelled")
    ingest_text(
        text,
        tool="calendar",
        source=ev.id,
        participants=participants,
        meet_link=ev.meet_url,
        title=ev.summary,
        tags=tags,
    )
