from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.slack.recipients import (
    extract_slack_message_body,
    extract_slack_recipient_name,
    resolve_slack_recipient,
    wants_slack_send_intent,
)


def test_extract_slack_recipient_name():
    assert extract_slack_recipient_name("send message to Sameer saying hello") == "Sameer"
    assert extract_slack_recipient_name("dm john saying hi") == "john"
    assert extract_slack_recipient_name("check latest message from varys what it saying") == ""
    assert extract_slack_recipient_name("message to Sameer saying hello") == "Sameer"


def test_wants_slack_send_intent():
    assert wants_slack_send_intent("send message to Sameer saying hello") is True
    assert wants_slack_send_intent("check latest message from varys what it saying") is False
    assert wants_slack_send_intent("check latest message of varys what it saying") is False
    assert wants_slack_send_intent("tell me latest message from varys in regionpunjab-internal channel") is False


def test_extract_slack_message_body():
    assert extract_slack_message_body("send message to Sameer saying hello there") == "hello there"
    assert extract_slack_message_body("message: ping me") == "ping me"


def test_resolve_slack_recipient_from_contacts(monkeypatch):
    monkeypatch.setattr(
        "tempa.channels.slack.recipients.search_contacts",
        lambda q, limit=10: [
            {"id": "slack:U123", "name": "Sameer Sheikh", "source": "slack"},
        ],
    )
    resolved = resolve_slack_recipient("sameer")
    assert resolved["user_id"] == "U123"
    assert "Sameer" in resolved["name"]


@pytest.mark.asyncio
async def test_channel_agent_sends_to_named_recipient():
    from tempa.agents.specialists import run_channel_agent

    with (
        patch("tempa.channels.slack.recipients.resolve_slack_recipient") as mock_resolve,
        patch("tempa.channels.slack.outbound.open_dm_for_user", new_callable=AsyncMock) as mock_open,
        patch("tempa.channels.slack.outbound.send_slack_message", new_callable=AsyncMock) as mock_send,
    ):
        mock_resolve.return_value = {"user_id": "U123", "name": "Sameer Sheikh"}
        mock_open.return_value = "D123"
        mock_send.return_value = {"status": "sent"}

        result = await run_channel_agent(
            "send message to Sameer saying hello",
            {
                "channel": "slack",
                "slack_privileged": True,
                "inbound_slack": True,
                "user_message": "send message to Sameer saying hello",
            },
        )

    payload = __import__("json").loads(result)
    assert payload["status"] == "sent"
    mock_send.assert_awaited_once()
    assert mock_send.await_args.args[0] == "D123"
    assert mock_send.await_args.args[1] == "hello"
