"""Calendar re-join helpers in job_store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tempa.meet.job_store import should_retry_calendar_join


def test_should_retry_when_calendar_event_still_active():
    now = datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc)
    statuses = {
        "mid": {
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "status": "completed",
            "started_at": (now - timedelta(minutes=10)).isoformat(),
            "calendar_event_end": (now + timedelta(hours=1)).isoformat(),
        }
    }
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value=statuses):
        with patch("tempa.meet.job_store.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert should_retry_calendar_join("https://meet.google.com/abc-defg-hij") is True


def test_should_not_retry_during_cooldown():
    now = datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc)
    statuses = {
        "mid": {
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "status": "failed",
            "started_at": (now - timedelta(minutes=1)).isoformat(),
            "calendar_event_end": (now + timedelta(hours=1)).isoformat(),
        }
    }
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value=statuses):
        with patch("tempa.meet.job_store.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            assert should_retry_calendar_join("https://meet.google.com/abc-defg-hij") is False
