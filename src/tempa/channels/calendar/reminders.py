from __future__ import annotations

import datetime as dt
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from tempa.channels.calendar.ingest import ingest_calendar_event
from tempa.channels.calendar.oauth import load_calendar_client
from tempa.channels.whatsapp.outbound import send_whatsapp_message
from tempa.channels.whatsapp.reply import load_default_whatsapp_number
from tempa.core.events import event_bus
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ReminderState:
    sent_keys: set[str] = field(default_factory=set)
    joined_keys: set[str] = field(default_factory=set)


def _state_path() -> Path:
    return get_settings().sessions_dir / "calendar" / "reminders_sent.json"


def load_reminder_state() -> ReminderState:
    path = _state_path()
    if not path.exists():
        return ReminderState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReminderState(
            sent_keys=set(data.get("sent_keys", [])),
            joined_keys=set(data.get("joined_keys", [])),
        )
    except Exception:
        return ReminderState()


def save_reminder_state(state: ReminderState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sent_keys": sorted(state.sent_keys), "joined_keys": sorted(state.joined_keys)}),
        encoding="utf-8",
    )


def _desktop_notify(title: str, body: str) -> None:
    try:
        subprocess.run(["notify-send", title, body], check=False, timeout=5)
    except Exception:
        logger.debug("Desktop notification unavailable")


def _reminder_key(event_id: str, start: dt.datetime, minutes_before: int) -> str:
    return f"{event_id}|{start.isoformat()}|{minutes_before}"


async def _maybe_auto_join(ev, state: ReminderState) -> None:
    """FR-CAL-05: auto-join Meet on reminder when configured."""
    settings = get_settings()
    if not settings.meet_auto_join_on_reminder or not ev.meet_url:
        return
    join_key = f"join|{ev.id}|{ev.start.isoformat()}"
    if join_key in state.joined_keys:
        return
    from tempa.meet.service import schedule_meeting_join

    try:
        schedule_meeting_join(ev.meet_url, title=ev.summary)
        state.joined_keys.add(join_key)
        await event_bus.publish_json("calendar", "meet_join_on_reminder", ev.summary)
    except Exception as exc:
        logger.warning("Auto-join on reminder failed: %s", exc)


async def poll_reminders_once(state: ReminderState) -> int:
    settings = get_settings()
    client = load_calendar_client()
    if client is None:
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    window_end = now + dt.timedelta(minutes=settings.reminder_minutes_before + 2)
    events = client.list_upcoming_events(calendar_id="primary", time_min=now, time_max=window_end)
    sent = 0
    number = load_default_whatsapp_number()

    for ev in events:
        ingest_calendar_event(ev)
        start = ev.start.astimezone(dt.timezone.utc)
        delta = (start - now).total_seconds() / 60.0
        if delta < 0 or delta > settings.reminder_minutes_before:
            continue
        key = _reminder_key(ev.id, start, settings.reminder_minutes_before)
        if key in state.sent_keys:
            continue
        state.sent_keys.add(key)
        msg = f"Reminder: *{ev.summary}* starts in {int(delta)} min."
        if ev.meet_url:
            msg += f"\nJoin: {ev.meet_url}"
            await _maybe_auto_join(ev, state)
        _desktop_notify("Tempa reminder", msg)
        if number:
            await send_whatsapp_message(number, msg, source_channel="whatsapp_auto_reply")
        await event_bus.publish_json("calendar", "reminder", ev.summary)
        sent += 1

    if sent or state.joined_keys:
        save_reminder_state(state)
    return sent
