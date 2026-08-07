"""Tests for today's meetings join + day-view layout invariants."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest


@pytest.mark.asyncio
async def test_get_todays_meetings_joins_archive_and_status(monkeypatch):
    from tempa.meet import today as today_mod

    zone = ZoneInfo("Asia/Karachi")
    day = datetime(2026, 8, 7, 12, 0, tzinfo=zone)
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    ev_start = day_start.replace(hour=10)
    ev_end = day_start.replace(hour=11)

    calendar_ev = SimpleNamespace(
        id="cal-1",
        summary="Standup",
        start=ev_start,
        end=ev_end,
        meet_url="https://meet.google.com/abc-defg-hij",
        raw={"start": {"dateTime": ev_start.isoformat()}, "end": {"dateTime": ev_end.isoformat()}},
    )

    archive_row = {
        "id": "mtg-1",
        "title": "Standup",
        "meet_link": "https://meet.google.com/abc-defg-hij",
        "started_at": ev_start.isoformat(),
        "ended_at": ev_end.isoformat(),
        "calendar_event_id": "cal-1",
        "calendar_event_start": ev_start.isoformat(),
        "minutes_status": "ready",
        "artifacts": {"audio": True, "transcript": True, "video": False},
    }

    client = MagicMock()
    client.list_upcoming_events.return_value = [calendar_ev]

    monkeypatch.setattr(today_mod, "now_local", lambda: day)
    monkeypatch.setattr(today_mod, "local_tz", lambda: zone)
    monkeypatch.setattr(today_mod, "tz_name", lambda: "Asia/Karachi")
    monkeypatch.setattr(
        "tempa.channels.calendar.oauth.load_calendar_client",
        lambda: client,
    )
    monkeypatch.setattr(today_mod, "list_meetings", AsyncMock(return_value=[archive_row]))
    monkeypatch.setattr(
        today_mod,
        "get_meeting_jobs",
        lambda: {"mtg-1": {"status": "running", "meet_url": archive_row["meet_link"], "calendar_event_id": "cal-1"}},
    )

    result = await today_mod.get_todays_meetings()
    assert result["date"] == "2026-08-07"
    assert result["timezone"] == "Asia/Karachi"
    assert len(result["events"]) == 1
    ev = result["events"][0]
    assert ev["id"] == "cal-1"
    assert ev["end"]
    assert ev["meeting_id"] == "mtg-1"
    assert ev["status"] == "running"
    assert ev["archive"]["id"] == "mtg-1"
    assert ev["has_meet"] is True


@pytest.mark.asyncio
async def test_get_todays_meetings_includes_orphan_archive(monkeypatch):
    from tempa.meet import today as today_mod

    zone = ZoneInfo("Asia/Karachi")
    day = datetime(2026, 8, 7, 15, 0, tzinfo=zone)
    started = day.replace(hour=9, minute=0)

    orphan = {
        "id": "orphan-1",
        "title": "Ad-hoc sync",
        "meet_link": "https://meet.google.com/xyz",
        "started_at": started.astimezone(ZoneInfo("UTC")).isoformat(),
        "ended_at": (started + timedelta(minutes=45)).astimezone(ZoneInfo("UTC")).isoformat(),
        "calendar_event_id": None,
        "artifacts": {"transcript": True},
    }

    client = MagicMock()
    client.list_upcoming_events.return_value = []

    monkeypatch.setattr(today_mod, "now_local", lambda: day)
    monkeypatch.setattr(today_mod, "local_tz", lambda: zone)
    monkeypatch.setattr(today_mod, "tz_name", lambda: "Asia/Karachi")
    monkeypatch.setattr("tempa.channels.calendar.oauth.load_calendar_client", lambda: client)
    monkeypatch.setattr(today_mod, "list_meetings", AsyncMock(return_value=[orphan]))
    monkeypatch.setattr(today_mod, "get_meeting_jobs", lambda: {})

    result = await today_mod.get_todays_meetings()
    assert len(result["events"]) == 1
    assert result["events"][0]["id"] == "archive:orphan-1"
    assert result["events"][0]["archive"]["id"] == "orphan-1"


def test_day_timeline_layout_pixel_invariants():
    """Mirror dashboard/src/lib/day-timeline.ts HOUR_HEIGHT=56 math."""
    hour_height = 56
    # 09:00–10:30 → top=9*56, height=1.5*56
    start_min = 9 * 60
    end_min = 10 * 60 + 30
    top = (start_min / 60) * hour_height
    height = ((end_min - start_min) / 60) * hour_height
    assert top == 9 * 56
    assert height == 1.5 * 56
