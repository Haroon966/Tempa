from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def slack_sync_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _sample_users():
    return [
        {
            "id": "U1",
            "name": "alice",
            "deleted": False,
            "is_bot": False,
            "profile": {"display_name": "Alice", "email": "alice@example.com"},
        },
        {
            "id": "U2",
            "name": "bot",
            "deleted": False,
            "is_bot": True,
            "profile": {"display_name": "Bot"},
        },
    ]


def _sample_channels():
    return [
        {"id": "D123", "is_im": True, "user": "U1"},
        {"id": "C456", "name": "general", "is_im": False},
    ]


def _sample_messages():
    return [
        {"ts": "1000.1", "user": "U1", "text": "hello"},
        {"ts": "1000.2", "user": "U1", "text": "world", "reply_count": 1},
    ]


@patch("tempa.channels.slack.snapshot.refresh_slack_snapshot")
@patch("tempa.channels.slack.sync.ingest_slack_message")
@patch("tempa.channels.slack.sync.iter_thread_replies")
@patch("tempa.channels.slack.sync.iter_conversation_messages")
@patch("tempa.channels.slack.sync.list_conversations")
@patch("tempa.channels.slack.sync.list_users")
@patch("tempa.channels.slack.sync.load_slack_client")
@patch("tempa.channels.slack.sync.sync_slack_contacts_blocking")
def test_sync_slack_once_ingests_messages_and_contacts(
    mock_contacts,
    mock_client_loader,
    mock_list_users,
    mock_list_conversations,
    mock_iter_messages,
    mock_iter_replies,
    mock_ingest,
    mock_snapshot,
    slack_sync_env,
):
    mock_contacts.return_value = {"status": "ok", "count": 1}
    mock_client = MagicMock()
    mock_client_loader.return_value = mock_client
    mock_list_users.return_value = _sample_users()
    mock_list_conversations.return_value = _sample_channels()
    mock_iter_messages.side_effect = [
        iter(_sample_messages()),
        iter([]),
    ]
    mock_iter_replies.return_value = iter([{"ts": "1000.3", "user": "U1", "text": "reply"}])
    mock_snapshot.return_value = {"status": "ok"}

    from tempa.channels.slack.sync import sync_slack_once_blocking

    result = sync_slack_once_blocking(full=True)

    assert result["status"] == "ok"
    assert result["new_messages"] >= 2
    assert result["contacts"]["status"] == "ok"
    assert result["contacts"]["count"] == 1
    assert mock_ingest.call_count >= 2


@patch("tempa.channels.slack.sync.load_slack_client")
def test_sync_skipped_without_token(mock_client_loader, tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    from tempa.settings import get_settings

    get_settings.cache_clear()

    from tempa.channels.slack.sync import sync_slack_once_blocking

    result = sync_slack_once_blocking()
    assert result["status"] == "skipped"
    get_settings.cache_clear()


def test_ingest_slack_message_skips_bots():
    from tempa.channels.slack.ingest import ingest_slack_message

    result = ingest_slack_message(
        {"bot_id": "B1", "text": "hi", "ts": "1.0"},
        channel_id="C1",
    )
    assert result["chunks_created"] == 0


def test_message_to_text_resolves_mentions():
    from tempa.channels.slack.ingest import message_to_text

    text = message_to_text(
        {"user": "U1", "text": "hey <@U2>", "ts": "1700000000.0"},
        channel_name="general",
        user_names={"U1": "Alice", "U2": "Bob"},
    )
    assert "Alice" in text
    assert "@Bob" in text


def test_build_slack_context_pack(slack_sync_env):
    from tempa.channels.slack.snapshot import save_slack_snapshot
    from tempa.channels.slack.context import build_slack_context_pack, format_slack_context_for_prompt

    save_slack_snapshot(
        {
            "channels": [{"id": "D1", "name": "Alice"}],
            "recent_messages": [
                {"channel": "Alice", "user": "Alice", "text": "hi", "ts": "1700000000.0"}
            ],
            "last_sync_at": "2026-01-01T00:00:00+00:00",
        }
    )
    pack = build_slack_context_pack()
    prompt = format_slack_context_for_prompt(pack)
    assert "Alice" in prompt
    assert "hi" in prompt
