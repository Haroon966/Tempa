"""Tests for meet scheduler readiness."""

from __future__ import annotations

from unittest.mock import patch

from tempa.meet.scheduler import meet_readiness, should_skip_event
from tempa.channels.calendar.client import CalendarEvent
from datetime import datetime, timezone


def test_should_skip_event_by_keyword():
    ev = CalendarEvent(
        id="1",
        summary="Focus time — no meetings",
        start=datetime.now(timezone.utc),
        end=datetime.now(timezone.utc),
        meet_url="https://meet.google.com/x",
        raw={},
    )
    assert should_skip_event(ev) is True


def test_meet_readiness_not_ready_without_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_dirs()

    with patch("tempa.meet.scheduler.has_recording_consent", return_value=False):
        with patch("tempa.meet.scheduler.google_connection_status", return_value={"connected": True}):
            r = meet_readiness()
    assert r.ready is False
    assert r.consent is False
