"""Tests for calendar meet trigger window (join active meetings)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from tempa.channels.calendar.client import CalendarEvent
from tempa.channels.calendar.poller import find_triggerable_meet_events


def _event(
    *,
    event_id: str = "ev1",
    summary: str = "Standup",
    start: datetime,
    end: datetime,
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        summary=summary,
        start=start,
        end=end,
        meet_url="https://meet.google.com/abc-defg-hij",
        raw={"status": "confirmed", "start": {"dateTime": start.isoformat()}},
    )


def test_triggerable_active_meeting_mid_session():
    now = datetime(2026, 7, 1, 10, 30, tzinfo=timezone.utc)
    ev = _event(
        start=now - timedelta(minutes=45),
        end=now + timedelta(minutes=15),
    )

    client = MagicMock()
    client.list_upcoming_events.return_value = [ev]

    with patch("tempa.channels.calendar.poller.load_calendar_client", return_value=client):
        with patch("tempa.channels.calendar.poller.dt.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timezone = timezone
            mock_dt.timedelta = timedelta
            result = find_triggerable_meet_events(
                lookback_hours=12,
                trigger_before_minutes=2,
            )

    assert len(result) == 1
    assert result[0].summary == "Standup"


def test_triggerable_future_meeting_before_start():
    now = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    ev = _event(
        start=now + timedelta(minutes=1),
        end=now + timedelta(minutes=31),
    )

    client = MagicMock()
    client.list_upcoming_events.return_value = [ev]

    with patch("tempa.channels.calendar.poller.load_calendar_client", return_value=client):
        with patch("tempa.channels.calendar.poller.dt.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timezone = timezone
            mock_dt.timedelta = timedelta
            result = find_triggerable_meet_events(trigger_before_minutes=2)

    assert len(result) == 1


def test_not_triggerable_after_meeting_ended():
    now = datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc)
    ev = _event(
        start=now - timedelta(hours=1),
        end=now - timedelta(minutes=5),
    )

    client = MagicMock()
    client.list_upcoming_events.return_value = [ev]

    with patch("tempa.channels.calendar.poller.load_calendar_client", return_value=client):
        with patch("tempa.channels.calendar.poller.dt.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timezone = timezone
            mock_dt.timedelta = timedelta
            result = find_triggerable_meet_events()

    assert result == []


def test_not_triggerable_too_far_before_start():
    now = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    ev = _event(
        start=now + timedelta(hours=2),
        end=now + timedelta(hours=3),
    )

    client = MagicMock()
    client.list_upcoming_events.return_value = [ev]

    with patch("tempa.channels.calendar.poller.load_calendar_client", return_value=client):
        with patch("tempa.channels.calendar.poller.dt.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timezone = timezone
            mock_dt.timedelta = timedelta
            result = find_triggerable_meet_events(trigger_before_minutes=2)

    assert result == []
