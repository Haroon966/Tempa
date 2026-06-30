from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.jira.drafts import context_key_from_slack_dm, load_draft
from tempa.channels.jira.tickets import handle_jira_ticket_message
from tempa.channels.slack.context import should_handle_channel_thread
from tempa.channels.slack.conversation import bot_participated_in_thread, record_conversation_turn
from tempa.channels.slack.reply import handle_inbound_slack
from tempa.channels.slack.varys_bridge import enrich_slack_context


@pytest.fixture
def ticket_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    from tempa.settings import get_settings
    from tempa.channels.jira.session import save_jira_session_config

    get_settings.cache_clear()
    save_jira_session_config(
        base_url="https://acme.atlassian.net",
        email="dev@acme.com",
        default_project="ENG",
        api_token="secret",
    )
    yield
    get_settings.cache_clear()


def test_enrich_slack_context_channel_mention_thread_root():
    ctx = enrich_slack_context(
        {"user": "U1", "channel": "C1", "ts": "3.0", "channel_type": "channel"},
        {},
    )
    assert ctx["slack_thread_ts"] == "3.0"
    assert ctx["slack_is_dm"] is False


def test_enrich_slack_context_dm_stable():
    ctx = enrich_slack_context(
        {"user": "U1", "channel": "D123", "ts": "2.0", "channel_type": "im"},
        {},
    )
    assert ctx["slack_is_dm"] is True
    assert ctx["slack_thread_ts"] == "2.0"


def test_bot_participated_in_thread():
    record_conversation_turn(
        role="assistant",
        text="preview ready",
        channel_id="C1",
        thread_ts="9.0",
        conversation_key="9.0",
    )
    assert bot_participated_in_thread("C1", "9.0") is True
    assert bot_participated_in_thread("C1", "8.0") is False


def test_dm_conversation_key_groups_turns():
    from tempa.channels.slack.conversation import conversation_thread_key, get_recent_messages

    key = conversation_thread_key(channel_id="D555", thread_ts="1.0", is_dm=True)
    assert key == "D555"
    record_conversation_turn(
        role="user",
        text="first",
        channel_id="D555",
        thread_ts="1.0",
        conversation_key=key,
    )
    record_conversation_turn(
        role="user",
        text="second",
        channel_id="D555",
        thread_ts="2.0",
        conversation_key=key,
    )
    msgs = get_recent_messages(10, channel_id="D555", conversation_key=key)
    texts = [m["text"] for m in msgs]
    assert "first" in texts
    assert "second" in texts


def test_should_handle_channel_thread_after_bot_reply():
    record_conversation_turn(
        role="assistant",
        text="On it",
        channel_id="C_GEN",
        thread_ts="100.0",
        conversation_key="100.0",
    )
    event = {"channel": "C_GEN", "thread_ts": "100.0", "user": "U2", "text": "yes please"}
    assert should_handle_channel_thread(event, "yes please") is True


@pytest.mark.asyncio
async def test_dm_multi_turn_jira_draft(ticket_env):
    ctx_base = {
        "channel": "slack",
        "slack_user_id": "U1",
        "slack_channel_id": "D555",
        "slack_is_dm": True,
    }

    with patch("tempa.channels.jira.tickets.ticket_feature_enabled", return_value=True), patch(
        "tempa.channels.jira.tickets.ensure_jira_users_fresh", new_callable=AsyncMock, return_value=None
    ), patch("tempa.channels.jira.tickets.ensure_contacts_fresh", new_callable=AsyncMock, return_value=None), patch(
        "tempa.channels.jira.tickets.resolve_jira_user"
    ) as mock_resolve, patch("tempa.channels.jira.tickets.find_similar_issues", return_value=[]):
        mock_resolve.return_value.account_id = "abc"
        mock_resolve.return_value.display_name = "Haroon"
        mock_resolve.return_value.email = "h@co.com"
        mock_resolve.return_value.ambiguous = []
        mock_resolve.return_value.missing = False
        mock_resolve.return_value.needs_input = ""
        mock_resolve.return_value.source = "live"

        await handle_jira_ticket_message(
            "create ticket assign to Haroon: fix login",
            {**ctx_base, "slack_thread_ts": "1.0", "thread_ts": "1.0"},
        )
        with patch("tempa.channels.jira.tickets.create_issue") as mock_create, patch(
            "tempa.channels.jira.tickets._check_rate_limit", return_value=True
        ):
            mock_create.return_value = {"status": "ok", "key": "ENG-7", "url": "https://x/browse/ENG-7"}
            reply = await handle_jira_ticket_message(
                "yes",
                {**ctx_base, "slack_thread_ts": "2.0", "thread_ts": "2.0"},
            )

    assert "ENG-7" in reply
    assert load_draft(context_key_from_slack_dm("D555")) is not None


@pytest.mark.asyncio
async def test_channel_thread_followup_without_mention(ticket_env, tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    record_conversation_turn(
        role="assistant",
        text="**Jira ticket preview**",
        channel_id="C_TEAM",
        thread_ts="50.0",
        conversation_key="50.0",
    )

    say = AsyncMock()
    with patch("tempa.channels.jira.tickets.ticket_feature_enabled", return_value=True), patch(
        "tempa.channels.jira.tickets.ensure_jira_users_fresh", new_callable=AsyncMock, return_value=None
    ), patch("tempa.channels.jira.tickets.ensure_contacts_fresh", new_callable=AsyncMock, return_value=None), patch(
        "tempa.channels.jira.tickets.create_issue"
    ) as mock_create, patch("tempa.channels.jira.tickets._check_rate_limit", return_value=True), patch(
        "tempa.channels.jira.tickets.resolve_jira_user"
    ) as mock_resolve, patch("tempa.channels.jira.tickets.find_similar_issues", return_value=[]):
        mock_resolve.return_value.account_id = "abc"
        mock_resolve.return_value.display_name = "Haroon"
        mock_resolve.return_value.email = ""
        mock_resolve.return_value.ambiguous = []
        mock_resolve.return_value.missing = False
        mock_resolve.return_value.needs_input = ""
        mock_resolve.return_value.source = "live"
        mock_create.return_value = {"status": "ok", "key": "ENG-8", "url": "https://x/browse/ENG-8"}

        await handle_inbound_slack(
            {
                "user": "U1",
                "channel": "C_TEAM",
                "channel_type": "channel",
                "text": "create ticket for Haroon: api timeout",
                "ts": "50.1",
                "thread_ts": "50.0",
            },
            event_type="app_mention",
            event_id="Ev200",
            say=say,
        )
        result = await handle_inbound_slack(
            {
                "user": "U1",
                "channel": "C_TEAM",
                "channel_type": "channel",
                "text": "yes",
                "ts": "50.2",
                "thread_ts": "50.0",
            },
            event_type="message",
            event_id="Ev201",
            say=say,
        )

    assert result.get("jira_ticket") is True or "ENG-8" in str(result.get("reply", ""))
    say.assert_awaited()
