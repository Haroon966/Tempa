from __future__ import annotations

from unittest.mock import MagicMock, patch

from tempa.channels.slack.lookup import (
    lookup_latest_slack_message,
    parse_slack_read_query,
    wants_slack_read_intent,
)


def test_wants_slack_read_intent():
    assert wants_slack_read_intent("check latest message from varys what it saying") is True
    assert wants_slack_read_intent("send message to Sameer saying hello") is False
    assert wants_slack_read_intent("# regionpunjab-internal in this channel") is True


def test_parse_slack_read_query():
    parsed = parse_slack_read_query(
        "check latest message from varys what it saying tell me it is in regionpunjab-internal channel"
    )
    assert parsed["channel"] == "regionpunjab-internal"
    assert parsed["user"] == "varys"
    parsed = parse_slack_read_query("# regionpunjab-internal  in this channel")
    assert parsed["channel"] == "regionpunjab-internal"


def test_channel_match_score():
    from tempa.channels.slack.lookup import _channel_match_score, find_channel_by_hint

    assert _channel_match_score("regionpunjab-internal", "region-punjab") == 0
    assert _channel_match_score("region-punjab", "region-punjab") == 100
    assert _channel_match_score("regionpunjab-internal", "regionpunjab-internal") == 100


def test_parse_slack_read_query_ignores_stop_words():
    parsed = parse_slack_read_query("latest message from the in regionpunjab-internal channel")
    assert parsed["user"] == ""
    assert parsed["channel"] == "regionpunjab-internal"


@patch("tempa.channels.slack.lookup.load_slack_client")
@patch("tempa.channels.slack.lookup.find_channel_by_hint")
@patch("tempa.channels.slack.lookup.resolve_slack_recipient")
@patch("tempa.channels.slack.lookup.list_users")
@patch("tempa.channels.slack.lookup.iter_conversation_messages")
def test_lookup_bot_message_from_varys(
    mock_history,
    mock_users,
    mock_resolve,
    mock_find_channel,
    mock_client,
):
    mock_client.return_value = MagicMock()
    mock_find_channel.return_value = ("C123", "regionpunjab-internal")
    mock_resolve.return_value = {}
    mock_users.return_value = []
    mock_history.return_value = [
        {
            "user": "UBOT",
            "bot_id": "B1",
            "username": "varys",
            "text": "Deploy is blocked until QA signs off.",
            "ts": "1782384000.0",
        },
        {"user": "U111", "text": "other", "ts": "1782383000.0"},
    ]

    result = lookup_latest_slack_message(
        "check latest message from varys in regionpunjab-internal channel"
    )

    assert result["status"] == "ok"
    assert "Deploy is blocked" in result["message"]


@patch("tempa.channels.slack.lookup.load_slack_client")
@patch("tempa.channels.slack.lookup.find_channel_by_hint")
@patch("tempa.channels.slack.lookup.resolve_slack_recipient")
@patch("tempa.channels.slack.lookup.list_users")
@patch("tempa.channels.slack.lookup.iter_conversation_messages")
def test_lookup_latest_slack_message(
    mock_history,
    mock_users,
    mock_resolve,
    mock_find_channel,
    mock_client,
):
    mock_client.return_value = MagicMock()
    mock_find_channel.return_value = ("C123", "regionpunjab-internal")
    mock_resolve.return_value = {"user_id": "U999", "name": "Varys"}
    mock_users.return_value = [{"id": "U999", "profile": {"display_name": "Varys"}}]
    mock_history.return_value = [
        {"user": "U999", "text": "Deploy is blocked until QA signs off.", "ts": "1782384000.0"},
        {"user": "U111", "text": "other", "ts": "1782383000.0"},
    ]

    result = lookup_latest_slack_message(
        "check latest message from varys in regionpunjab-internal channel"
    )

    assert result["status"] == "ok"
    assert result["user"] == "Varys"
    assert "Deploy is blocked" in result["message"]
