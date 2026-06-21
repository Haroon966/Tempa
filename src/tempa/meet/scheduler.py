"""Calendar-driven Meet join scheduling with readiness checks."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.calendar.client import CalendarEvent
from tempa.channels.calendar.status import google_connection_status
from tempa.core.events import event_bus
from tempa.meet.consent import has_recording_consent
from tempa.meet.job_store import has_active_job_for_url
from tempa.meet.service import schedule_meeting_join_async
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class MeetReadiness:
    ready: bool
    consent: bool
    meet_auth: bool
    google_connected: bool
    detail: str


def meet_readiness() -> MeetReadiness:
    settings = get_settings()
    consent = has_recording_consent()
    meet_auth = settings.google_storage_state_path.exists()
    google = google_connection_status()
    google_ok = bool(google.get("connected"))
    ready = consent and meet_auth and google_ok
    parts: list[str] = []
    if not consent:
        parts.append("recording consent not granted")
    if not meet_auth:
        parts.append("Meet browser auth missing (run `tempa meet-auth`)")
    if not google_ok:
        parts.append(google.get("detail") or "Google Calendar not connected")
    return MeetReadiness(
        ready=ready,
        consent=consent,
        meet_auth=meet_auth,
        google_connected=google_ok,
        detail="; ".join(parts) if parts else "ready",
    )


def _failures_path() -> Path:
    return get_settings().sessions_dir / "calendar" / "join_failures.json"


def _record_join_failure(event: CalendarEvent, reason: str) -> None:
    path = _failures_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries = data[-49:]
        except Exception:
            entries = []
    entries.append(
        {
            "event_id": event.id,
            "summary": event.summary,
            "meet_url": event.meet_url,
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _desktop_notify(title: str, body: str) -> None:
    try:
        subprocess.run(["notify-send", title, body], check=False, timeout=5)
    except Exception:
        pass


async def _notify_join_failure(event: CalendarEvent, reason: str) -> None:
    title = f"Could not join: {event.summary[:60]}"
    body = reason[:200]
    _desktop_notify(title, body)
    try:
        from tempa.channels.whatsapp.outbound import send_whatsapp_message
        from tempa.channels.whatsapp.reply import load_default_whatsapp_number

        number = load_default_whatsapp_number()
        if number:
            await send_whatsapp_message(
                number,
                f"*{title}*\n{body}",
                source_channel="whatsapp_auto_reply",
            )
    except Exception:
        logger.debug("WhatsApp join failure notify skipped", exc_info=True)
    await event_bus.publish_json("calendar", "meet_join_failed", {"summary": event.summary, "reason": reason})


def extract_attendee_emails(event: CalendarEvent) -> list[str]:
    raw = event.raw if isinstance(event.raw, dict) else {}
    attendees = raw.get("attendees") or []
    emails: list[str] = []
    for att in attendees:
        if isinstance(att, dict):
            email = att.get("email")
            if isinstance(email, str) and email.strip():
                emails.append(email.strip().lower())
    return sorted(set(emails))


def compute_duration_seconds(event: CalendarEvent, *, buffer_minutes: int = 10) -> int:
    start = event.start.astimezone(timezone.utc)
    end = event.end.astimezone(timezone.utc)
    delta = (end - start).total_seconds() + buffer_minutes * 60
    return max(int(delta), 900)


def should_skip_event(event: CalendarEvent) -> bool:
    settings = get_settings()
    keywords = getattr(settings, "meet_skip_keywords", None) or []
    title = (event.summary or "").lower()
    for kw in keywords:
        if kw and re.search(re.escape(kw.lower()), title):
            return True
    return False


def calendar_event_metadata(event: CalendarEvent) -> dict[str, Any]:
    return {
        "calendar_event_id": event.id,
        "calendar_event_start": event.start.astimezone(timezone.utc).isoformat(),
        "calendar_event_end": event.end.astimezone(timezone.utc).isoformat(),
        "attendee_emails": extract_attendee_emails(event),
        "duration_seconds": compute_duration_seconds(event),
    }


async def schedule_join_for_calendar_event(
    event: CalendarEvent,
    *,
    notify_number: str | None = None,
) -> str | None:
    """Schedule a Meet join for a calendar event. Returns meeting_id or None on skip/failure."""
    settings = get_settings()
    if not getattr(settings, "meet_auto_join_enabled", True):
        logger.debug("Meet auto-join disabled; skipping %s", event.summary)
        return None
    if not event.meet_url or "meet.google.com" not in event.meet_url:
        return None
    if should_skip_event(event):
        logger.info("Skipping meet join for %s (title filter)", event.summary)
        return None
    if has_active_job_for_url(event.meet_url):
        logger.debug("Active job already exists for %s", event.meet_url)
        return None

    readiness = meet_readiness()
    if not readiness.ready:
        reason = readiness.detail
        logger.warning("Meet join not ready for %s: %s", event.summary, reason)
        _record_join_failure(event, reason)
        await _notify_join_failure(event, reason)
        return None

    meta = calendar_event_metadata(event)
    try:
        meeting_id = await schedule_meeting_join_async(
            event.meet_url,
            title=event.summary,
            notify_number=notify_number,
            calendar_event_id=meta["calendar_event_id"],
            calendar_event_start=meta["calendar_event_start"],
            calendar_event_end=meta["calendar_event_end"],
            attendee_emails=meta["attendee_emails"],
            duration_seconds=meta["duration_seconds"],
        )
        await event_bus.publish_json("calendar", "meet_join_scheduled", event.summary)
        return meeting_id
    except Exception as exc:
        reason = str(exc)
        logger.exception("Failed to schedule meet join for %s", event.summary)
        _record_join_failure(event, reason)
        await _notify_join_failure(event, reason)
        return None
