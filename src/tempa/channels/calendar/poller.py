from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

from tempa.channels.calendar.client import CalendarEvent
from tempa.channels.calendar.ingest import ingest_calendar_event
from tempa.channels.calendar.oauth import load_calendar_client
from tempa.core.events import event_bus
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

TriggerCallback = Callable[[CalendarEvent], Awaitable[None]]


def _state_path() -> Path:
    return get_settings().sessions_dir / "calendar" / "poller_state.json"


@dataclass
class PollerState:
    triggered_keys: set[str] = field(default_factory=set)


def load_poller_state() -> PollerState:
    path = _state_path()
    if not path.exists():
        return PollerState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = data.get("triggered_keys") or []
        return PollerState(triggered_keys=set(keys))
    except Exception:
        return PollerState()


def save_poller_state(state: PollerState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"triggered_keys": sorted(state.triggered_keys)}, indent=2),
        encoding="utf-8",
    )


def _event_key(ev: CalendarEvent) -> str:
    start_utc = ev.start.astimezone(dt.timezone.utc).isoformat()
    return f"{ev.id}|{start_utc}"


def find_triggerable_meet_events(
    *,
    window_minutes: int = 120,
    trigger_before_minutes: int = 2,
    trigger_after_start_minutes: int = 10,
) -> list[CalendarEvent]:
    """Return Google Calendar events with Meet links inside the trigger window."""
    client = load_calendar_client()
    if client is None:
        return []

    now_utc = dt.datetime.now(dt.timezone.utc)
    lookback = dt.timedelta(minutes=window_minutes)
    upcoming = client.list_upcoming_events(
        calendar_id="primary",
        time_min=now_utc,
        time_max=now_utc + dt.timedelta(minutes=window_minutes),
    )
    recent = client.list_upcoming_events(
        calendar_id="primary",
        time_min=now_utc - lookback,
        time_max=now_utc,
    )

    events: list[CalendarEvent] = []
    seen: set[str] = set()
    for ev in recent + upcoming:
        key = _event_key(ev)
        if key in seen:
            continue
        seen.add(key)
        if not ev.meet_url or "meet.google.com" not in ev.meet_url:
            continue
        status = ev.raw.get("status") if isinstance(ev.raw, dict) else None
        if status == "cancelled":
            continue
        start_obj = ev.raw.get("start") if isinstance(ev.raw, dict) else None
        is_all_day = isinstance(start_obj, dict) and start_obj.get("date") and not start_obj.get("dateTime")
        if is_all_day:
            continue

        start_utc = ev.start.astimezone(dt.timezone.utc)
        end_utc = ev.end.astimezone(dt.timezone.utc)
        trigger_window_start = start_utc - dt.timedelta(minutes=trigger_before_minutes)
        trigger_window_end = start_utc + dt.timedelta(minutes=trigger_after_start_minutes)
        if trigger_window_start <= now_utc <= trigger_window_end and now_utc < end_utc:
            events.append(ev)
    return events


async def poll_once(state: PollerState, on_trigger: TriggerCallback) -> list[CalendarEvent]:
    import asyncio

    from tempa.meet.job_store import has_active_job_for_url

    settings = get_settings()
    triggered: list[CalendarEvent] = []
    events = await asyncio.to_thread(
        find_triggerable_meet_events,
        trigger_before_minutes=settings.meet_trigger_before_minutes,
        trigger_after_start_minutes=settings.meet_trigger_after_start_minutes,
    )
    for ev in events:
        key = _event_key(ev)
        if key in state.triggered_keys:
            continue
        if ev.meet_url and has_active_job_for_url(ev.meet_url):
            continue
        triggered.append(ev)
        state.triggered_keys.add(key)
        save_poller_state(state)
        try:
            ingest_calendar_event(ev)
        except Exception:
            logger.warning("Calendar ingest failed for %s (continuing with auto-join)", ev.summary, exc_info=True)
        await event_bus.publish_json("calendar", "meet_trigger", ev.summary)
        logger.info("Calendar auto-join: triggering %s (%s)", ev.summary, ev.meet_url)
        try:
            await on_trigger(ev)
        except Exception:
            logger.exception("Calendar auto-join trigger failed for %s", ev.summary)
    return triggered
