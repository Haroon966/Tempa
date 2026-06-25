from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tempa.channels.calendar.context import build_meeting_context_pack, format_meeting_context_for_prompt


def test_meeting_context_pack_sections():
    now = datetime.now(timezone.utc)
    events = [
        {
            "id": "up1",
            "summary": "Future Sync",
            "start": (now + timedelta(hours=2)).isoformat(),
            "end": (now + timedelta(hours=3)).isoformat(),
            "status": "confirmed",
            "description": "Plan Q3",
            "attendees": ["a@example.com"],
            "meet_url": "https://meet.google.com/x",
        },
        {
            "id": "past1",
            "summary": "Yesterday Call",
            "start": (now - timedelta(days=1)).isoformat(),
            "end": (now - timedelta(days=1, hours=-1)).isoformat(),
            "status": "confirmed",
            "description": "",
            "attendees": [],
        },
        {
            "id": "c1",
            "summary": "Canceled Standup",
            "start": now.isoformat(),
            "end": now.isoformat(),
            "status": "cancelled",
            "description": "",
            "attendees": [],
        },
    ]
    with patch("tempa.channels.calendar.context.load_calendar_snapshot", return_value={"events": events}):
        with patch("tempa.channels.calendar.context._meetings_by_calendar_id", return_value={}):
            with patch("tempa.channels.calendar.context._fetch_live_meeting_block", return_value=""):
                pack = build_meeting_context_pack(days_past=7, days_future=7)

    assert pack["upcoming"]
    assert pack["recently_canceled"]
    compact = format_meeting_context_for_prompt(pack, full=False)
    assert "Calendar today" in compact or "Future Sync" in compact
    full = format_meeting_context_for_prompt(pack, full=True)
    assert "Recently canceled" in full
    assert "Canceled Standup" in full
