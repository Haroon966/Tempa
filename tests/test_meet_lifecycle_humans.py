"""Human-only leave logic for Meet lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tempa.meet.lifecycle import MeetingEndTracker, check_meeting_ended


def _page(*, names=None, leave_btn: int = 1, url: str = "https://meet.google.com/abc-defg-hij"):
    page = MagicMock()
    page.url = url

    def locator(selector):
        loc = MagicMock()
        # End-of-meeting UI signals must be absent; leave button present while in-call.
        if "Leave" in str(selector):
            loc.count = AsyncMock(return_value=leave_btn)
        else:
            loc.count = AsyncMock(return_value=0)
        return loc

    page.locator = MagicMock(side_effect=locator)
    page.evaluate = AsyncMock(return_value=names if names is not None else [])
    return page


@pytest.mark.asyncio
async def test_humans_present_does_not_end():
    page = _page(names=["Alice", "Tempa", "Rumi"])
    tracker = MeetingEndTracker(alone_grace_seconds=60.0)
    ended = await check_meeting_ended(page, tracker=tracker)
    assert ended is False
    assert tracker.alone_since is None
    assert tracker.last_human_count == 1


@pytest.mark.asyncio
async def test_only_bots_starts_grace_then_ends(monkeypatch):
    page = _page(names=["Tempa", "Rumi", "Notetaker"])
    tracker = MeetingEndTracker(alone_grace_seconds=30.0)

    mono = {"t": 1000.0}
    monkeypatch.setattr("tempa.meet.lifecycle.time.monotonic", lambda: mono["t"])

    ended = await check_meeting_ended(page, tracker=tracker)
    assert ended is False
    assert tracker.alone_since == 1000.0

    mono["t"] = 1040.0
    ended = await check_meeting_ended(page, tracker=tracker)
    assert ended is True


@pytest.mark.asyncio
async def test_alone_before_event_start_does_not_end(monkeypatch):
    page = _page(names=["Tempa"])
    tracker = MeetingEndTracker(alone_grace_seconds=60.0)
    event_start_ts = 9_999_999_999.0
    monkeypatch.setattr("tempa.meet.lifecycle.time.time", lambda: 1_000_000_000.0)

    ended = await check_meeting_ended(page, tracker=tracker, event_start_ts=event_start_ts)

    assert ended is False
    assert tracker.alone_since is None
