from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tempa.channels.calendar.client import CalendarEvent
from tempa.channels.calendar.sync import (
    event_to_snapshot,
    load_calendar_snapshot,
    remove_event_from_snapshot,
    save_calendar_snapshot,
    sync_calendar_snapshot,
)


def _event(
    event_id: str = "ev1",
    *,
    summary: str = "Standup",
    status: str = "confirmed",
    updated: str = "2026-06-21T10:00:00Z",
) -> CalendarEvent:
    start = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 21, 10, 30, tzinfo=timezone.utc)
    return CalendarEvent(
        id=event_id,
        summary=summary,
        start=start,
        end=end,
        meet_url="https://meet.google.com/abc-defg-hij",
        raw={
            "status": status,
            "updated": updated,
            "description": "Review roadmap",
            "attendees": [{"email": "a@example.com"}],
        },
    )


def test_event_to_snapshot_includes_agenda():
    row = event_to_snapshot(_event())
    assert row["summary"] == "Standup"
    assert row["description"] == "Review roadmap"
    assert "a@example.com" in row["attendees"]


def test_sync_reconciles_new_and_removed_events(tmp_path, monkeypatch):
    snap_path = tmp_path / "calendar" / "snapshot.json"
    monkeypatch.setattr("tempa.channels.calendar.sync._snapshot_path", lambda: snap_path)

    save_calendar_snapshot(
        {
            "last_sync_at": "old",
            "events": [{"id": "gone", "summary": "Old", "updated": "1"}],
        }
    )

    client = MagicMock()
    client.list_upcoming_events.return_value = [_event("ev-new")]

    with patch("tempa.channels.calendar.sync.load_calendar_client", return_value=client):
        with patch("tempa.channels.calendar.sync.ingest_calendar_event") as ingest:
            with patch("tempa.channels.calendar.sync.purge_calendar_event", return_value=2) as purge:
                result = sync_calendar_snapshot()

    assert result["status"] == "ok"
    assert result["ingested"] == 1
    assert purge.call_count >= 1
    ingest.assert_called_once()
    saved = load_calendar_snapshot()
    assert any(e["id"] == "ev-new" for e in saved["events"])
    assert not any(e["id"] == "gone" for e in saved["events"])


def test_sync_purges_cancelled_events(tmp_path, monkeypatch):
    snap_path = tmp_path / "calendar" / "snapshot.json"
    monkeypatch.setattr("tempa.channels.calendar.sync._snapshot_path", lambda: snap_path)

    client = MagicMock()
    client.list_upcoming_events.return_value = [_event(status="cancelled")]

    with patch("tempa.channels.calendar.sync.load_calendar_client", return_value=client):
        with patch("tempa.channels.calendar.sync.purge_calendar_event", return_value=1) as purge:
            with patch("tempa.channels.calendar.sync.ingest_calendar_event") as ingest:
                sync_calendar_snapshot()

    purge.assert_called()
    ingest.assert_not_called()


def test_remove_event_from_snapshot(tmp_path, monkeypatch):
    snap_path = tmp_path / "calendar" / "snapshot.json"
    monkeypatch.setattr("tempa.channels.calendar.sync._snapshot_path", lambda: snap_path)
    save_calendar_snapshot({"events": [{"id": "a"}, {"id": "b"}]})
    remove_event_from_snapshot("a")
    data = json.loads(snap_path.read_text())
    assert data["events"] == [{"id": "b"}]
