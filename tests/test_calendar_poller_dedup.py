"""Tests for calendar poller deduplication."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.calendar.client import CalendarEvent
from tempa.channels.calendar.poller import PollerState, _event_key, poll_once, save_poller_state


def _event(event_id: str = "ev1", summary: str = "Standup") -> CalendarEvent:
    start = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 21, 10, 30, tzinfo=timezone.utc)
    return CalendarEvent(
        id=event_id,
        summary=summary,
        start=start,
        end=end,
        meet_url="https://meet.google.com/abc-defg-hij",
        raw={"status": "confirmed", "start": {"dateTime": start.isoformat()}},
    )


@pytest.mark.asyncio
async def test_poller_skips_already_triggered_keys():
    ev = _event()
    key = _event_key(ev)
    state = PollerState(triggered_keys={key})
    triggered_events: list[CalendarEvent] = []

    async def on_trigger(event: CalendarEvent) -> None:
        triggered_events.append(event)

    with patch("tempa.channels.calendar.poller.find_triggerable_meet_events", return_value=[ev]):
        with patch("tempa.meet.job_store.has_active_job_for_url", return_value=False):
            result = await poll_once(state, on_trigger)

    assert result == []
    assert triggered_events == []
    assert key in state.triggered_keys


@pytest.mark.asyncio
async def test_poller_triggers_once_and_persists_key(tmp_path, monkeypatch):
    ev = _event()
    state = PollerState()
    calls: list[CalendarEvent] = []

    async def on_trigger(event: CalendarEvent) -> None:
        calls.append(event)

    state_file = tmp_path / "poller_state.json"

    def fake_save(st: PollerState) -> None:
        save_poller_state(st)

    monkeypatch.setattr("tempa.channels.calendar.poller._state_path", lambda: state_file)

    with patch("tempa.channels.calendar.poller.find_triggerable_meet_events", return_value=[ev]):
        with patch("tempa.meet.job_store.has_active_job_for_url", return_value=False):
            with patch("tempa.channels.calendar.poller.ingest_calendar_event"):
                with patch("tempa.core.events.event_bus.publish_json", new_callable=AsyncMock):
                    first = await poll_once(state, on_trigger)
                    second = await poll_once(state, on_trigger)

    assert len(first) == 1
    assert len(second) == 0
    assert len(calls) == 1
    assert state_file.exists()
