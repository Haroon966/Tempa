from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.meet.notify import (
    format_meeting_summary,
    is_punjab_daily_sync,
    notify_meeting_completed,
)


def test_format_meeting_summary_includes_sections():
    minutes = {
        "tldr": "Shipped compression middleware.",
        "decisions": [{"summary": "Use 25KB compression on attendance API"}],
        "action_items": [{"owner": "Mavia", "task": "Deploy filter UI", "due": "Friday"}],
        "open_questions": [{"question": "What is PISP/PSRP?"}],
    }
    text = format_meeting_summary(
        "Team Punjab – Daily Sync",
        minutes,
        meet_link="https://meet.google.com/pdd-pnhn-ogp",
        for_slack=True,
    )
    assert "Team Punjab" in text
    assert "Shipped compression" in text
    assert "Decisions" in text
    assert "Action items" in text
    assert "Open questions" in text
    assert "pdd-pnhn-ogp" in text


def test_is_punjab_daily_sync_matches_title_variants():
    assert is_punjab_daily_sync("Team Punjab – Daily Sync")
    assert is_punjab_daily_sync("team punjab - daily sync")
    assert not is_punjab_daily_sync("Optional: Sense-making Sessions")


@pytest.mark.asyncio
async def test_notify_meeting_completed_posts_punjab_sync_to_slack_channel():
    minutes = {"tldr": "Pilot feedback loops agreed."}
    record = {
        "title": "Team Punjab – Daily Sync",
        "meet_link": "https://meet.google.com/fng-gkpu-rrq",
        "youtube_url": "https://youtu.be/B5aNKybppEA",
    }

    with (
        patch("tempa.settings.get_settings") as mock_settings,
        patch("tempa.meet.notify._send_slack_summary_to_hints", new_callable=AsyncMock, return_value="sent") as mock_send,
        patch("tempa.channels.slack.outbound.open_dm_for_user", new_callable=AsyncMock, return_value="D1"),
        patch("tempa.channels.slack.outbound.send_slack_message", new_callable=AsyncMock, return_value={"status": "sent"}),
    ):
        settings = mock_settings.return_value
        settings.meet_auto_send_summary_whatsapp = False
        settings.meet_auto_send_summary_slack = True
        settings.slack_owner_user_id = "U1"
        settings.meet_punjab_daily_sync_slack_channel = "region-punjab"

        results = await notify_meeting_completed(record, minutes)

    assert results["slack"] == "sent"
    assert results["slack_punjab_channel"] == "sent"
    mock_send.assert_awaited_once()
    hints, msg = mock_send.await_args.args
    assert hints == ("region-punjab", "regionpunjab-internal")
    assert "Team Punjab" in msg
    assert "Pilot feedback loops agreed." in msg


@pytest.mark.asyncio
async def test_notify_meeting_completed_skips_punjab_channel_for_other_meetings():
    with (
        patch("tempa.settings.get_settings") as mock_settings,
        patch("tempa.meet.notify._send_slack_summary_to_hints", new_callable=AsyncMock) as mock_send,
    ):
        settings = mock_settings.return_value
        settings.meet_auto_send_summary_whatsapp = False
        settings.meet_auto_send_summary_slack = False
        settings.slack_owner_user_id = ""
        settings.meet_punjab_daily_sync_slack_channel = "region-punjab"

        results = await notify_meeting_completed({"title": "Weekly Planning"}, {"tldr": "Done."})

    assert "slack_punjab_channel" not in results
    mock_send.assert_not_awaited()
