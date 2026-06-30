from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.slack.reply import handle_inbound_slack


@pytest.mark.asyncio
async def test_guest_can_create_jira_ticket():
    event = {
        "user": "UGUEST",
        "channel": "D123",
        "channel_type": "im",
        "ts": "100.200",
        "text": "create jira ticket assign to Haroon: fix API",
    }

    with patch("tempa.channels.slack.reply.mark_inbound_seen", return_value=True), patch(
        "tempa.channels.slack.reply.has_assistant_reply_for", return_value=False
    ), patch("tempa.channels.slack.reply.is_privileged_slack_user", return_value=False), patch(
        "tempa.channels.jira.tickets.ticket_feature_enabled", return_value=True
    ), patch(
        "tempa.channels.jira.intent.wants_jira_ticket_create", return_value=True
    ), patch(
        "tempa.channels.jira.tickets.handle_jira_ticket_message",
        new_callable=AsyncMock,
        return_value="Ticket preview ready",
    ), patch("tempa.channels.slack.reply.send_slack_message", new_callable=AsyncMock) as mock_send, patch(
        "tempa.channels.slack.reply.record_conversation_turn"
    ), patch("tempa.channels.slack.reply.touch_event"):
        result = await handle_inbound_slack(event, event_id="evt-1")

    assert result.get("jira_ticket") is True
    assert result.get("skipped_coordinator") is True
    mock_send.assert_called_once()
