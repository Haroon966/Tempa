"""Event coverage rules for calendar Meet auto-join."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tempa.meet.job_store import event_needs_coverage, should_retry_calendar_join


def _patch_now(now: datetime):
    return patch("tempa.meet.job_store.datetime", wraps=datetime)


def test_needs_coverage_when_no_prior_jobs():
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value={}):
        with patch("tempa.meet.job_store._active_job_for_url_unlocked", return_value=None):
            assert (
                event_needs_coverage(
                    "https://meet.google.com/abc-defg-hij",
                    calendar_event_id="evt1",
                    event_end=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                )
                is True
            )


def test_no_coverage_after_empty():
    now = datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc)
    statuses = {
        "mid": {
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "calendar_event_id": "evt1",
            "status": "empty",
            "segment_count": 0,
            "started_at": (now - timedelta(minutes=10)).isoformat(),
            "calendar_event_end": (now + timedelta(hours=1)).isoformat(),
        }
    }
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value=statuses):
        with patch("tempa.meet.job_store._active_job_for_url_unlocked", return_value=None):
            with patch("tempa.meet.job_store.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k) if a else now
                # Keep real datetime constructor behaviour via wraps-like helpers
                mock_dt.min = datetime.min
                mock_dt.fromisoformat = datetime.fromisoformat
                assert (
                    event_needs_coverage(
                        "https://meet.google.com/abc-defg-hij",
                        calendar_event_id="evt1",
                        event_end=(now + timedelta(hours=1)).isoformat(),
                    )
                    is False
                )


def test_no_coverage_after_completed_with_speech():
    now = datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc)
    statuses = {
        "mid": {
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "calendar_event_id": "evt1",
            "status": "completed",
            "segment_count": 12,
            "started_at": (now - timedelta(minutes=10)).isoformat(),
            "calendar_event_end": (now + timedelta(hours=1)).isoformat(),
        }
    }
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value=statuses):
        with patch("tempa.meet.job_store._active_job_for_url_unlocked", return_value=None):
            with patch("tempa.meet.job_store.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.min = datetime.min
                mock_dt.fromisoformat = datetime.fromisoformat
                assert (
                    event_needs_coverage(
                        "https://meet.google.com/abc-defg-hij",
                        calendar_event_id="evt1",
                        event_end=(now + timedelta(hours=1)).isoformat(),
                    )
                    is False
                )


def test_no_coverage_after_event_end_even_if_failed():
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    end = now - timedelta(minutes=5)
    statuses = {
        "mid": {
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "calendar_event_id": "evt1",
            "status": "failed",
            "segment_count": 0,
            "started_at": (now - timedelta(hours=2)).isoformat(),
            "calendar_event_end": end.isoformat(),
        }
    }
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value=statuses):
        with patch("tempa.meet.job_store._active_job_for_url_unlocked", return_value=None):
            with patch("tempa.meet.job_store.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.min = datetime.min
                mock_dt.fromisoformat = datetime.fromisoformat
                assert (
                    event_needs_coverage(
                        "https://meet.google.com/abc-defg-hij",
                        calendar_event_id="evt1",
                        event_end=end.isoformat(),
                    )
                    is False
                )


def test_coverage_after_failed_mid_event_without_speech():
    now = datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc)
    statuses = {
        "mid": {
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "calendar_event_id": "evt1",
            "status": "failed",
            "segment_count": 0,
            "started_at": (now - timedelta(minutes=10)).isoformat(),
            "calendar_event_end": (now + timedelta(hours=1)).isoformat(),
        }
    }
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value=statuses):
        with patch("tempa.meet.job_store._active_job_for_url_unlocked", return_value=None):
            with patch("tempa.meet.job_store.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.min = datetime.min
                mock_dt.fromisoformat = datetime.fromisoformat
                assert (
                    event_needs_coverage(
                        "https://meet.google.com/abc-defg-hij",
                        calendar_event_id="evt1",
                        event_end=(now + timedelta(hours=1)).isoformat(),
                    )
                    is True
                )


def test_interrupted_does_not_rejoin_while_awaiting_finalize():
    now = datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc)
    with patch("tempa.meet.job_store._active_job_for_url_unlocked", return_value="mid"):
        assert (
            event_needs_coverage(
                "https://meet.google.com/abc-defg-hij",
                calendar_event_id="evt1",
                event_end=(now + timedelta(hours=1)).isoformat(),
            )
            is False
        )


def test_should_retry_wrapper_uses_coverage():
    now = datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc)
    statuses = {
        "mid": {
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "status": "empty",
            "segment_count": 0,
            "started_at": (now - timedelta(minutes=10)).isoformat(),
            "calendar_event_end": (now + timedelta(hours=1)).isoformat(),
            "calendar_event_id": "evt1",
        }
    }
    with patch("tempa.meet.job_store._read_statuses_unlocked", return_value=statuses):
        with patch("tempa.meet.job_store._active_job_for_url_unlocked", return_value=None):
            with patch("tempa.meet.job_store.datetime") as mock_dt:
                mock_dt.now.return_value = now
                mock_dt.min = datetime.min
                mock_dt.fromisoformat = datetime.fromisoformat
                assert should_retry_calendar_join("https://meet.google.com/abc-defg-hij") is False
