from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tempa.channels.slack import users
from tempa.channels.slack.outbound import _split_text, send_slack_message
from tempa.channels.slack.reply import handle_inbound_slack
from tempa.channels.slack.session import mark_event_seen, mark_inbound_seen, slack_configured


@pytest.fixture(autouse=True)
def _reset_slack_session(monkeypatch):
    from tempa.channels.slack import session

    session._seen_event_ids.clear()
    session._last_error = None
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SLACK_OWNER_USER_ID", "U_OWNER")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "")
    monkeypatch.setenv("SLACK_ALLOW_ALL", "false")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_split_text_chunks_long_reply():
    text = "a" * 5000
    chunks = _split_text(text, limit=100)
    assert len(chunks) > 1
    assert "".join(chunks) == text


def test_is_allowed_slack_user_owner():
    assert users.is_allowed_slack_user("U_OWNER") is True
    assert users.is_allowed_slack_user("U_OTHER") is False


def test_is_allowed_slack_user_extra(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U_FRIEND,U_GUEST")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    assert users.is_allowed_slack_user("U_FRIEND") is True


def test_mark_event_seen_dedupes():
    assert mark_event_seen("Ev001") is True
    assert mark_event_seen("Ev001") is False


def test_mark_inbound_seen_dedupes_by_message_ts():
    assert mark_inbound_seen(channel_id="D1", message_ts="1.0") is True
    assert mark_inbound_seen(channel_id="D1", message_ts="1.0") is False
    assert mark_inbound_seen(event_id="Ev002", channel_id="D1", message_ts="2.0") is True


@pytest.mark.asyncio
async def test_owner_dm_triggers_coordinator_and_say(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    say = AsyncMock()
    with patch("tempa.agents.graph.run_coordinator_full", new_callable=AsyncMock) as mock_coord:
        mock_coord.return_value = {"response": "Hello from Tempa"}
        result = await handle_inbound_slack(
            {
                "user": "U_OWNER",
                "channel": "D123",
                "channel_type": "im",
                "text": "hi",
                "ts": "1.0",
            },
            event_type="message",
            event_id="Ev100",
            say=say,
        )

    assert result["handled"] == 1
    say.assert_awaited_once_with(text="Hello from Tempa")
    mock_coord.assert_awaited_once()


@pytest.mark.asyncio
async def test_guest_dm_triggers_coordinator(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    say = AsyncMock()
    with patch("tempa.agents.graph.run_coordinator_full", new_callable=AsyncMock) as mock_coord:
        mock_coord.return_value = {"response": "Hello guest"}
        result = await handle_inbound_slack(
            {
                "user": "U_STRANGER",
                "channel": "D999",
                "channel_type": "im",
                "text": "hello",
                "ts": "2.0",
            },
            event_type="message",
            event_id="Ev101",
            say=say,
        )

    assert result["handled"] == 1
    mock_coord.assert_awaited_once()
    ctx = mock_coord.await_args.args[1]
    assert ctx["slack_privileged"] is False
    say.assert_awaited_once_with(text="Hello guest")


@pytest.mark.asyncio
async def test_guest_private_integration_gets_coming_soon(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    say = AsyncMock()
    with patch("tempa.agents.graph.run_coordinator_full", new_callable=AsyncMock) as mock_coord:
        result = await handle_inbound_slack(
            {
                "user": "U_STRANGER",
                "channel": "D999",
                "channel_type": "im",
                "text": "what's on my calendar today?",
                "ts": "2.1",
            },
            event_type="message",
            event_id="Ev103",
            say=say,
        )

    assert result["handled"] == 1
    assert result.get("skipped_coordinator") is True
    assert "slack yet" in result["reply"].lower()
    mock_coord.assert_not_called()
    say.assert_awaited_once()


@pytest.mark.asyncio
async def test_app_mention_replies_in_thread(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    say = AsyncMock()
    with patch("tempa.agents.graph.run_coordinator_full", new_callable=AsyncMock) as mock_coord:
        mock_coord.return_value = {"response": "On it"}
        result = await handle_inbound_slack(
            {
                "user": "U_COLLEAGUE",
                "channel": "C_GENERAL",
                "text": "<@UBOT> what time is it?",
                "ts": "3.0",
            },
            event_type="app_mention",
            event_id="Ev102",
            say=say,
        )

    assert result["handled"] == 1
    say.assert_awaited_once_with(text="On it", thread_ts="3.0")


@pytest.mark.asyncio
async def test_duplicate_event_skipped():
    say = AsyncMock()
    event = {
        "user": "U_OWNER",
        "channel": "D123",
        "channel_type": "im",
        "text": "ping",
        "ts": "4.0",
    }
    with patch("tempa.agents.graph.run_coordinator_full", new_callable=AsyncMock) as mock_coord:
        mock_coord.return_value = {"response": "pong"}
        first = await handle_inbound_slack(event, event_id="EvDup", say=say)
        second = await handle_inbound_slack(event, event_id="EvDup", say=say)

    assert first["handled"] == 1
    assert second.get("duplicate") is True
    assert mock_coord.await_count == 1


@pytest.mark.asyncio
async def test_slack_send_pending_action(monkeypatch):
    with (
        patch("tempa.core.pending_actions.create_pending_action") as mock_create,
        patch("tempa.core.notifications.notify", new_callable=AsyncMock),
    ):
        mock_create.return_value = {"id": "pa-1"}
        result = await send_slack_message("C1", "hello", source_channel="coordinator")

    assert result["status"] == "pending"
    mock_create.assert_called_once()
    args = mock_create.call_args
    assert args[0][0] == "slack_send"
    assert args[0][1]["channel"] == "C1"


@pytest.mark.asyncio
async def test_slack_send_auto_reply_skips_pending(monkeypatch):
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value=MagicMock(data={"ok": True}))
    with patch("tempa.channels.slack.outbound._get_client", new_callable=AsyncMock, return_value=client):
        result = await send_slack_message("D1", "auto", source_channel="slack_auto_reply")

    assert result["status"] == "sent"
    client.chat_postMessage.assert_awaited()


def test_slack_configured_requires_both_tokens(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    assert slack_configured() is False

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    get_settings.cache_clear()
    assert slack_configured() is True


@pytest.mark.asyncio
async def test_varys_slack_read_direct_reply(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    ctx = {
        "channel": "slack",
        "inbound_slack": True,
        "slack_user_id": "U_OWNER",
        "slack_channel_id": "D123",
    }
    channel_json = json.dumps(
        {
            "status": "ok",
            "channel": "regionpunjab-internal",
            "user": "Varys",
            "message": "Deploy is blocked until QA signs off.",
            "timestamp": "2026-06-26 12:00 UTC",
        }
    )

    with patch("tempa.agents.specialists.run_channel_agent", new_callable=AsyncMock) as mock_channel:
        mock_channel.return_value = channel_json
        from tempa.channels.slack.direct_reply import try_slack_direct_reply

        reply = await try_slack_direct_reply(
            "check latest message from varys in regionpunjab-internal channel",
            ctx,
        )

    assert reply is not None
    assert "Deploy is blocked" in reply
    assert "Varys" in reply


@pytest.mark.asyncio
async def test_pending_action_executor_slack_send(monkeypatch):
    from tempa.core.pending_actions import _run_executor

    with patch("tempa.channels.slack.outbound.send_slack_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "sent"}
        result = await _run_executor(
            "slack_send",
            {"channel": "C99", "text": "approved", "thread_ts": "1.1"},
        )

    assert result["status"] == "sent"
    mock_send.assert_awaited_once_with(
        "C99",
        "approved",
        thread_ts="1.1",
        require_user_confirmation=False,
    )
