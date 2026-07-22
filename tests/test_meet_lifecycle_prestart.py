"""Pre-start lobby should not alone-exit before calendar event start."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tempa.meet.lifecycle import MeetingEndTracker, check_meeting_ended


@pytest.mark.asyncio
async def test_alone_before_event_start_does_not_end(monkeypatch):
    page = MagicMock()
    page.url = "https://meet.google.com/abc-defg-hij"

    def locator(selector):
        loc = MagicMock()
        loc.count = AsyncMock(return_value=1 if "Leave" in str(selector) else 0)
        return loc

    page.locator = MagicMock(side_effect=locator)
    page.evaluate = AsyncMock(return_value=["Tempa"])

    tracker = MeetingEndTracker(alone_grace_seconds=60.0)
    # Event starts far in the future
    event_start_ts = 9_999_999_999.0
    monkeypatch.setattr("tempa.meet.lifecycle.time.time", lambda: 1_000_000_000.0)

    ended = await check_meeting_ended(page, tracker=tracker, event_start_ts=event_start_ts)

    assert ended is False
    assert tracker.alone_since is None
