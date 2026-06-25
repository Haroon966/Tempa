from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tempa.channels.calendar.client import CalendarEvent, GoogleCalendar
from tempa.channels.calendar.ingest import ingest_calendar_event
from tempa.channels.calendar.oauth import load_calendar_client

_CREATE_HINTS = re.compile(
    r"\b(?:make|create|schedule|add|set(?:\s+up)?|book)\b.*\b(?:meeting|event|appointment)\b",
    re.I,
)
_INVITE_CREATE_HINTS = re.compile(
    r"\b(?:send|email)\s+(?:an?\s+)?invite\b.*\b(?:meeting|calendar|calender)\b",
    re.I,
)
_SEND_INVITE_HINTS = re.compile(
    r"\b(?:send|resend|email)\b.*\b(?:invite|invitation)\b",
    re.I,
)
_ADD_GUEST_HINTS = re.compile(
    r"\b(?:add|invite)\b.*\b(?:as\s+)?(?:a\s+)?guest\b",
    re.I,
)
_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
_DELETE_HINTS = re.compile(
    r"\b(?:remove|delete|cancel|clear)\b",
    re.I,
)
_DELETE_TITLE_RE = re.compile(
    r"\b(?:remove|delete|cancel|clear)\s+(?:the\s+)?(.+?)\s+(?:meeting|metting|event|appointment)s?\b",
    re.I,
)
_DELETE_IT_RE = re.compile(r"\b(?:remove|delete|cancel|clear)\s+(?:it|them|that)\b", re.I)
_TIME_RE = re.compile(
    r"(?:around|at|on|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.I,
)
_TIME_FALLBACK_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
_TIME_RANGE_RE = re.compile(
    r"(?:around|at|from|@)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+to\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.I,
)
_DURATION_RE = re.compile(r"\b(\d+)\s*(?:min|mins|minutes?)\b", re.I)
_TITLE_NAME_RE = re.compile(r"\bname\s+(.+?)(?:\s*$)", re.I)
_GUEST_NAME_PATTERNS = (
    re.compile(r"\b(?:send\s+)?(?:an?\s+)?invite\s+to\s+(.+?)\s+for\b", re.I),
    re.compile(r"\binvite\s+(.+?)\s+to\s+(?:the\s+)?(?:meeting|calendar)\b", re.I),
    re.compile(r"\b(?:add|invite)\s+(.+?)\s+as\s+(?:a\s+)?guest\b", re.I),
    re.compile(r"\b(?:send|email)\s+(?:an?\s+)?invite\s+to\s+(.+?)(?:\s+at|\s*$|,|\.)", re.I),
    re.compile(r"\binvite\s+(.+?)\s+at\s+", re.I),
    re.compile(
        r"\b(?:meeting\s+)?(?:me\s+and|with)\s+([A-Za-z][\w\s\-']+?)(?:\s+for\s+\d|\s+at|\s+from|\s+\d|\s+to\s+\d|\s*$|,|\.)",
        re.I,
    ),
)


@dataclass
class CreateEventResult:
    ok: bool
    summary: str = ""
    when: str = ""
    start_at: datetime | None = None
    meet_url: str | None = None
    invited_attendees: list[str] | None = None
    error: str = ""
    event: CalendarEvent | None = None


@dataclass
class DeleteEventResult:
    ok: bool
    deleted: list[str] | None = None
    error: str = ""


@dataclass
class InviteEventResult:
    ok: bool
    summary: str = ""
    attendees: list[str] | None = None
    error: str = ""


def wants_create_event(text: str) -> bool:
    if _CREATE_HINTS.search(text):
        return True
    if _INVITE_CREATE_HINTS.search(text):
        return True
    if re.search(r"\bsend\b.*\binvite\b", text, re.I) and re.search(
        r"\bmeeting\b", text, re.I
    ):
        return True
    return False


def wants_send_calendar_invite(text: str) -> bool:
    lower = text.lower()
    if _SEND_INVITE_HINTS.search(text):
        return True
    if "invite" in lower and any(k in lower for k in ("calendar", "calender", "meeting")):
        if any(k in lower for k in ("send", "resend", "email", "guest")):
            return True
    return False


def wants_add_guest(text: str) -> bool:
    return bool(_ADD_GUEST_HINTS.search(text))


def wants_delete_event(text: str) -> bool:
    if not _DELETE_HINTS.search(text):
        return False
    if _DELETE_TITLE_RE.search(text):
        return True
    if _DELETE_IT_RE.search(text):
        return True
    if re.search(r"\b(?:meeting|metting|event|appointment|calendar)\b", text, re.I):
        return True
    return False


from tempa.core.timezone import local_tz, tz_name


def _local_tz():
    return local_tz()


def _tz_name() -> str:
    return tz_name()


def parse_delete_title(text: str, *, recent_texts: list[str] | None = None) -> str | None:
    match = _DELETE_TITLE_RE.search(text)
    if match:
        title = match.group(1).strip().rstrip(".")
        title = re.sub(r"\s+from\s+(?:the\s+)?cal(?:endar|ender).*$", "", title, flags=re.I).strip()
        if title:
            return title[:120]

    if _DELETE_IT_RE.search(text) and recent_texts:
        for msg in reversed(recent_texts):
            prior = parse_delete_title(msg)
            if prior:
                return prior
            created = parse_event_title(msg) if wants_create_event(msg) else None
            if created and created != "Meeting":
                return created

    quoted = re.search(r'["\']([^"\']+)["\']', text)
    if quoted and quoted.group(1).strip():
        return quoted.group(1).strip()[:120]
    return None


def parse_event_title(text: str) -> str:
    match = _TITLE_NAME_RE.search(text)
    if match:
        title = match.group(1).strip().rstrip(".")
        title = re.split(r"\s+with\s+|\s+to\s+|\s+for\s+|\s+at\s+(?:\d|today)", title, flags=re.I)[0]
        title = _EMAIL_RE.sub("", title).strip(" ,")
        title = re.sub(r"\s+(?:around|at|on)\s+.*$", "", title, flags=re.I).strip()
        if title:
            return title[:120]
    invite_match = re.search(
        r"\b(?:meeting|event)\s+(?:named|called|name)\s+(.+?)(?:\s+(?:to|with|for|at)\s+|\s*$)",
        text,
        re.I,
    )
    if invite_match and invite_match.group(1).strip():
        title = _EMAIL_RE.sub("", invite_match.group(1)).strip(" ,")
        if title:
            return title[:120]
    for_match = re.search(r"\bfor\s+(.+?)\s+meeting\b", text, re.I)
    if for_match and for_match.group(1).strip():
        title = for_match.group(1).strip()
        title = _DURATION_RE.sub("", title).strip(" ,")
        if title:
            return title[:120]
    for pattern in (
        r'(?:called|titled)\s+"([^"]+)"',
        r"(?:called|titled)\s+'([^']+)'",
        r"(?:called|titled)\s+([\w\s\-]+?)(?:\s+(?:at|around|on)\s+|\s*$)",
    ):
        match = re.search(pattern, text, re.I)
        if match and match.group(1).strip():
            return match.group(1).strip()[:120]
    named_for = re.search(r"\bfor\s+(?:\d+\s+minutes?\s+)?for\s+(.+?)\s*$", text, re.I)
    if named_for and named_for.group(1).strip():
        return named_for.group(1).strip()[:120]
    with_match = re.search(
        r"\b(?:me\s+and|with)\s+([A-Za-z][\w\s\-']+?)(?:\s+for\s+\d|\s+at|\s+from|\s+\d|\s+to\s+|\s*$|,|\.)",
        text,
        re.I,
    )
    if with_match and with_match.group(1).strip():
        guest = _clean_guest_name(with_match.group(1))
        if guest.lower() not in {"me", "them", "a", "an", "the"}:
            return f"Meeting with {guest.title()}"[:120]
    trailing_for = re.search(r"\bfor\s+(.+?)\s*$", text, re.I)
    if trailing_for:
        label = trailing_for.group(1).strip().rstrip(".")
        if label and not re.match(r"^\d+\s+minutes?$", label, re.I):
            return label[:120]
    return "Meeting"


def _clean_guest_name(name: str) -> str:
    cleaned = name.strip().rstrip(".,;")
    cleaned = re.sub(r"\s+for(?:\s+.*)?$", "", cleaned, flags=re.I).strip()
    return cleaned


_calendar_owner_cache: str | None = None


def get_calendar_owner_email() -> str:
    global _calendar_owner_cache
    if _calendar_owner_cache:
        return _calendar_owner_cache
    client = load_calendar_client()
    if client is None:
        return ""
    try:
        cal = client._service.calendars().get(calendarId="primary").execute()
        _calendar_owner_cache = str(cal.get("id") or "")
    except Exception:
        _calendar_owner_cache = ""
    return _calendar_owner_cache


def external_attendees_from_event_raw(raw: dict[str, Any]) -> list[str]:
    owner = get_calendar_owner_email().lower()
    from tempa.channels.gmail.recipients import is_excluded_guest_email

    guests: list[str] = []
    for att in raw.get("attendees") or []:
        email = str(att.get("email") or "").strip()
        if not email or att.get("organizer") or att.get("self"):
            continue
        if is_excluded_guest_email(email, owner=owner):
            continue
        if email.lower() not in {g.lower() for g in guests}:
            guests.append(email)
    return guests


def _resolve_name_to_email(name: str) -> str | None:
    if "@" in name:
        email = name.strip()
        from tempa.channels.gmail.recipients import is_excluded_guest_email

        owner = get_calendar_owner_email()
        if is_excluded_guest_email(email, owner=owner):
            return None
        return email

    cleaned = _clean_guest_name(name)
    from tempa.channels.gmail.recipients import resolve_guest_email_by_name

    owner = get_calendar_owner_email()
    for candidate in (cleaned, name.strip()):
        if not candidate:
            continue
        email = resolve_guest_email_by_name(candidate, owner=owner)
        if email:
            return email
    return None


def _attendee_names_from_text(text: str) -> list[str]:
    names: list[str] = []
    for pattern in _GUEST_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            name = _clean_guest_name(match.group(1))
            if name and "@" not in name and name.lower() not in {"the", "a", "an"}:
                names.append(name)
    if not names:
        loose = re.search(r"\bto\s+([A-Za-z][\w\s\-']{1,40}?)\s+for\s+", text, re.I)
        if loose:
            name = _clean_guest_name(loose.group(1))
            if name and "@" not in name:
                names.append(name)
    return names


def parse_event_duration(text: str, *, default: int = 60) -> int:
    time_range = parse_event_time_range(text)
    if time_range is not None:
        return time_range[1]
    match = _DURATION_RE.search(text)
    if not match:
        return default
    try:
        minutes = int(match.group(1))
    except ValueError:
        return default
    return max(5, min(minutes, 480))


def parse_attendee_emails(text: str, *, recent_texts: list[str] | None = None) -> list[str]:
    from tempa.channels.gmail.recipients import is_excluded_guest_email

    owner = get_calendar_owner_email()
    emails = [
        email
        for email in dict.fromkeys(_EMAIL_RE.findall(text))
        if not is_excluded_guest_email(email, owner=owner)
    ]
    if emails:
        return emails

    partial = re.search(
        r"\b(?:to|for|guest)\s+([\w.\-]+)(?:\s|$|\.|,)",
        text,
        re.I,
    )
    if partial:
        needle = partial.group(1).lower()
        for msg in reversed((recent_texts or []) + [text]):
            for email in _EMAIL_RE.findall(msg):
                if needle in email.lower() and not is_excluded_guest_email(email, owner=owner):
                    return [email]

    resolved: list[str] = []
    for name in _attendee_names_from_text(text):
        email = _resolve_name_to_email(name)
        if email and email not in resolved:
            resolved.append(email)

    if not resolved:
        for msg in reversed(recent_texts or []):
            for name in _attendee_names_from_text(msg):
                email = _resolve_name_to_email(name)
                if email and email not in resolved:
                    resolved.append(email)
    return resolved


def _parse_time_components(
    hour: int,
    minute: int,
    meridiem: str,
    *,
    now: datetime,
    inherit_meridiem: str = "",
) -> datetime:
    mer = (meridiem or inherit_meridiem or "").lower()
    if mer == "pm" and hour < 12:
        hour += 12
    if mer == "am" and hour == 12:
        hour = 0
    if not mer and hour < 8:
        hour += 12

    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= now - timedelta(minutes=5):
        start += timedelta(days=1)
    return start


def _parse_time_match(match: re.Match[str], *, now: datetime) -> datetime:
    return _parse_time_components(
        int(match.group(1)),
        int(match.group(2) or 0),
        (match.group(3) or "").lower(),
        now=now,
    )


def parse_event_time_range(text: str, *, now: datetime | None = None) -> tuple[datetime, int] | None:
    """Parse '11:30pm to 11:45pm' into (start, duration_minutes)."""
    match = _TIME_RANGE_RE.search(text)
    if not match:
        return None

    now = now or datetime.now(_local_tz())
    if now.tzinfo is None:
        now = now.replace(tzinfo=_local_tz())

    start_mer = (match.group(3) or "").lower()
    end_mer = (match.group(6) or start_mer or "").lower()
    start = _parse_time_components(
        int(match.group(1)),
        int(match.group(2) or 0),
        start_mer,
        now=now,
    )
    end = _parse_time_components(
        int(match.group(4)),
        int(match.group(5) or 0),
        end_mer,
        now=now,
        inherit_meridiem=start_mer,
    )
    duration = int((end - start).total_seconds() / 60)
    if duration <= 0:
        duration += 24 * 60
    return start, max(5, min(duration, 480))


def parse_event_start(text: str, *, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(_local_tz())
    if now.tzinfo is None:
        now = now.replace(tzinfo=_local_tz())

    time_range = parse_event_time_range(text, now=now)
    if time_range is not None:
        return time_range[0]

    matches = list(_TIME_RE.finditer(text))
    if not matches:
        matches = list(_TIME_FALLBACK_RE.finditer(text))
    if not matches:
        return None

    # When multiple times are mentioned, use the last one (often the corrected time).
    return _parse_time_match(matches[-1], now=now)


def format_calendar_error(exc: Exception) -> str:
    message = str(exc)
    if "accessNotConfigured" in message or "has not been used in project" in message:
        return (
            "Google Calendar API is not enabled for your Cloud project. "
            "Open Google Cloud Console → APIs & Services → Library → enable "
            "'Google Calendar API', wait 2 minutes, then try again."
        )
    if "insufficientPermissions" in message or "Insufficient Permission" in message:
        return (
            "Google token lacks calendar write permission. "
            "Disconnect Google in the Tempa dashboard and connect again."
        )
    if "invalid_grant" in message:
        return "Google session expired — reconnect Google in the Tempa dashboard."
    return message[:300]


def fetch_upcoming_summary(*, days: int = 2, limit: int = 6) -> str:
    try:
        from tempa.channels.calendar.context import build_meeting_context_pack, format_meeting_context_for_prompt

        pack = build_meeting_context_pack(days_future=max(days, 2))
        text = format_meeting_context_for_prompt(pack, full=False)
        if text:
            return text
    except Exception:
        pass
    client = load_calendar_client()
    if client is None:
        return "Google Calendar: not connected — connect in the Tempa dashboard."
    try:
        now = datetime.now(_local_tz())
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        events = client.list_upcoming_events(
            calendar_id="primary",
            time_min=now.astimezone(ZoneInfo("UTC")),
            time_max=(now + timedelta(days=days)).astimezone(ZoneInfo("UTC")),
            max_results=limit,
        )
        if not events:
            return "Calendar: nothing scheduled in the next 2 days."
        lines: list[str] = []
        for event in events[:limit]:
            start = event.start.astimezone(_local_tz())
            line = f"- {start.strftime('%a %H:%M')}: {event.summary}"
            if event.meet_url:
                line += f" — {event.meet_url}"
            lines.append(line)
        return "Upcoming calendar:\n" + "\n".join(lines)
    except Exception as exc:
        return f"Calendar error: {format_calendar_error(exc)}"


def create_calendar_event(
    *,
    summary: str,
    start: datetime,
    duration_minutes: int = 60,
    with_meet: bool = True,
    attendee_emails: list[str] | None = None,
) -> CreateEventResult:
    client = load_calendar_client()
    if client is None:
        return CreateEventResult(ok=False, error="Google Calendar not connected.")

    if start.tzinfo is None:
        start = start.replace(tzinfo=_local_tz())
    end = start + timedelta(minutes=duration_minutes)

    from tempa.channels.gmail.recipients import is_excluded_guest_email

    owner = get_calendar_owner_email()
    guest_emails = [
        email
        for email in (attendee_emails or [])
        if email and not is_excluded_guest_email(email, owner=owner)
    ]

    try:
        event = client.create_event(
            summary=summary,
            start=start,
            end=end,
            with_meet=with_meet,
            timezone=_tz_name(),
            attendee_emails=guest_emails or None,
        )
        invited = external_attendees_from_event_raw(event.raw or {})
        ingest_calendar_event(event)
        when = start.astimezone(_local_tz()).strftime("%a %H:%M")
        from tempa.channels.calendar.session_state import record_calendar_event

        record_calendar_event(
            {
                "event_id": event.id,
                "summary": summary,
                "when": when,
                "meet_url": event.meet_url,
                "attendees": invited,
            }
        )
        return CreateEventResult(
            ok=True,
            summary=summary,
            when=when,
            start_at=start,
            meet_url=event.meet_url,
            invited_attendees=invited,
            event=event,
        )
    except Exception as exc:
        return CreateEventResult(ok=False, error=format_calendar_error(exc))


def try_create_event_from_message(
    text: str,
    *,
    recent_texts: list[str] | None = None,
) -> CreateEventResult:
    if not wants_create_event(text):
        return CreateEventResult(ok=False, error="not a create request")

    title = parse_event_title(text)
    time_range = parse_event_time_range(text)
    if time_range is not None:
        start, duration = time_range
    else:
        start = parse_event_start(text)
        duration = parse_event_duration(text)
    if start is None:
        return CreateEventResult(
            ok=False,
            error="Could not parse meeting time — try e.g. 'create meeting at 5:10pm name Tempa Testing'.",
        )
    attendees = parse_attendee_emails(text, recent_texts=recent_texts)
    return create_calendar_event(
        summary=title,
        start=start,
        duration_minutes=duration,
        attendee_emails=attendees or None,
    )


def apply_calendar_actions_from_message(
    text: str,
    *,
    recent_texts: list[str] | None = None,
) -> dict[str, Any]:
    """Create, delete, or invite on Google Calendar. Shared by WhatsApp and dashboard agent."""
    successes: list[str] = []
    failures: list[str] = []
    action = "none"
    ok = False
    details: dict[str, Any] = {}

    delete_result = try_delete_event_from_message(text, recent_texts=recent_texts)
    if delete_result.error != "not a delete request":
        action = "deleted"
        if delete_result.ok and delete_result.deleted:
            names = ", ".join(f"'{name}'" for name in delete_result.deleted)
            successes.append(f"Deleted from calendar: {names}.")
            ok = True
            details["deleted"] = delete_result.deleted
        else:
            failures.append(f"Could not delete calendar event: {delete_result.error}")
            details["error"] = delete_result.error

    create_result = try_create_event_from_message(text, recent_texts=recent_texts)
    created_with_invites = False
    if create_result.error != "not a create request":
        action = "created"
        if create_result.ok:
            line = f"Created calendar event '{create_result.summary}' at {create_result.when}."
            invited = create_result.invited_attendees or []
            if invited:
                line += f" Calendar invite sent to {', '.join(invited)}."
                created_with_invites = True
            else:
                guest_names = _attendee_names_from_text(text)
                if not guest_names:
                    for msg in recent_texts or []:
                        guest_names.extend(_attendee_names_from_text(msg))
                if guest_names:
                    failures.append(
                        f"Could not send calendar invite: No guest email found for {guest_names[0]}. "
                        f"What's {guest_names[0]}'s email?"
                    )
                    details["unresolved_guests"] = guest_names
            if create_result.meet_url:
                line += f" Meet link: {create_result.meet_url}"
                job_id = schedule_meet_join_for_event(
                    create_result.meet_url,
                    summary=create_result.summary,
                    start=create_result.start_at,
                )
                if job_id:
                    line += f" Tempa is joining the Meet now (job {job_id[:8]}…)."
                    details["meet_job_id"] = job_id
            successes.append(line)
            ok = True
            details.update(
                {
                    "summary": create_result.summary,
                    "when": create_result.when,
                    "meet_url": create_result.meet_url,
                    "invited_attendees": invited,
                    "start_at": create_result.start_at.isoformat() if create_result.start_at else None,
                }
            )
        else:
            failures.append(f"Could not create calendar event: {create_result.error}")
            details["error"] = create_result.error

    invite_result = try_invite_guests_from_message(text, recent_texts=recent_texts)
    if invite_result.error != "not an invite request":
        action = "invited"
        if invite_result.ok:
            guests = ", ".join(invite_result.attendees or [])
            successes.append(f"Sent calendar invite for '{invite_result.summary}' to {guests}.")
            ok = True
            details["invited_attendees"] = invite_result.attendees
            details["summary"] = invite_result.summary
        elif not (create_result.ok and created_with_invites):
            failures.append(f"Could not send calendar invite: {invite_result.error}")
            details["error"] = invite_result.error

    return {
        "action": action,
        "ok": ok,
        "successes": successes,
        "failures": failures,
        **details,
    }


def should_auto_join_meet(start: datetime, *, within_minutes: int = 20) -> bool:
    """True when the meeting is soon enough that Tempa should join now."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=_local_tz())
    now = datetime.now(_local_tz())
    delta_min = (start - now).total_seconds() / 60.0
    return -5 <= delta_min <= within_minutes


def schedule_meet_join_for_event(
    meet_url: str,
    *,
    summary: str,
    start: datetime | None = None,
) -> str | None:
    if not meet_url:
        return None
    if start is not None and not should_auto_join_meet(start):
        return None
    from tempa.meet.service import schedule_meeting_join

    return schedule_meeting_join(meet_url, title=summary or "Meeting")


def find_events_by_title(title: str, *, days: int = 14) -> list[CalendarEvent]:
    client = load_calendar_client()
    if client is None:
        return []
    now = datetime.now(_local_tz())
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    events = client.list_upcoming_events(
        calendar_id="primary",
        time_min=now.astimezone(ZoneInfo("UTC")),
        time_max=(now + timedelta(days=days)).astimezone(ZoneInfo("UTC")),
        max_results=50,
    )
    needle = title.lower()
    return [event for event in events if needle in event.summary.lower()]


def delete_calendar_events_by_title(title: str) -> DeleteEventResult:
    client = load_calendar_client()
    if client is None:
        return DeleteEventResult(ok=False, error="Google Calendar not connected.")

    matches = find_events_by_title(title)
    if not matches:
        return DeleteEventResult(
            ok=False,
            error=f"No upcoming event matching '{title}' on your calendar.",
        )

    deleted: list[str] = []
    try:
        for event in matches:
            client.delete_event(event.id)
            deleted.append(event.summary)
            from tempa.channels.calendar.sync import remove_event_from_snapshot
            from tempa.rag.purge import purge_calendar_event

            purge_calendar_event(event.id)
            remove_event_from_snapshot(event.id)
    except Exception as exc:
        return DeleteEventResult(ok=False, error=format_calendar_error(exc))

    return DeleteEventResult(ok=True, deleted=deleted)


def try_delete_event_from_message(
    text: str,
    *,
    recent_texts: list[str] | None = None,
) -> DeleteEventResult:
    if not wants_delete_event(text):
        return DeleteEventResult(ok=False, error="not a delete request")

    title = parse_delete_title(text, recent_texts=recent_texts)
    if not title:
        return DeleteEventResult(
            ok=False,
            error="Which meeting should I remove? e.g. 'remove Tempa Testing meeting from calendar'.",
        )
    return delete_calendar_events_by_title(title)


def resolve_event_for_invite(
    text: str,
    *,
    recent_texts: list[str] | None = None,
) -> CalendarEvent | None:
    from tempa.channels.calendar.session_state import get_last_calendar_event

    last = get_last_calendar_event()
    event_id = last.get("event_id")
    if event_id:
        client = load_calendar_client()
        if client is None:
            return None
        try:
            return client.get_event(str(event_id))
        except Exception:
            pass

    for msg in reversed(recent_texts or []):
        if wants_create_event(msg):
            title = parse_event_title(msg)
            matches = find_events_by_title(title)
            if matches:
                return matches[0]
    return None


def send_calendar_invites(
    event: CalendarEvent,
    attendee_emails: list[str],
) -> InviteEventResult:
    client = load_calendar_client()
    if client is None:
        return InviteEventResult(ok=False, error="Google Calendar not connected.")
    if not attendee_emails:
        return InviteEventResult(ok=False, error="No guest email found.")

    try:
        updated = client.add_attendees(event.id, attendee_emails)
        from tempa.channels.calendar.session_state import get_last_calendar_event, record_calendar_event

        last = get_last_calendar_event()
        merged = list(dict.fromkeys((last.get("attendees") or []) + attendee_emails))
        record_calendar_event(
            {
                **last,
                "event_id": updated.id,
                "summary": updated.summary or event.summary,
                "attendees": merged,
            }
        )
        return InviteEventResult(ok=True, summary=updated.summary or event.summary, attendees=attendee_emails)
    except Exception as exc:
        return InviteEventResult(ok=False, error=format_calendar_error(exc))


def try_invite_guests_from_message(
    text: str,
    *,
    recent_texts: list[str] | None = None,
) -> InviteEventResult:
    if not wants_send_calendar_invite(text) and not wants_add_guest(text):
        return InviteEventResult(ok=False, error="not an invite request")

    attendees = parse_attendee_emails(text, recent_texts=recent_texts)
    if not attendees:
        return InviteEventResult(
            ok=False,
            error=(
                "No guest email found — use an email address or add the person to Google contacts "
                "(reconnect Google in Tempa → Connections to sync contacts)."
            ),
        )

    event = resolve_event_for_invite(text, recent_texts=recent_texts)
    if event is None:
        return InviteEventResult(
            ok=False,
            error="Could not find a recent meeting to invite guests to. Create the meeting first.",
        )
    return send_calendar_invites(event, attendees)
