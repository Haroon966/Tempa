from __future__ import annotations

from unittest.mock import MagicMock, patch

from tempa.channels.calendar.events import delete_calendar_events_by_title


def test_delete_calendar_events_purges_rag_and_snapshot():
    event = MagicMock()
    event.id = "ev-delete"
    event.summary = "Tempa Testing"

    client = MagicMock()
    with patch("tempa.channels.calendar.events.load_calendar_client", return_value=client):
        with patch("tempa.channels.calendar.events.find_events_by_title", return_value=[event]):
            with patch("tempa.rag.purge.purge_calendar_event", return_value=1) as purge:
                with patch("tempa.channels.calendar.sync.remove_event_from_snapshot") as remove_snap:
                    result = delete_calendar_events_by_title("Tempa Testing")

    assert result.ok is True
    client.delete_event.assert_called_once_with("ev-delete")
    purge.assert_called_once_with("ev-delete")
    remove_snap.assert_called_once_with("ev-delete")
