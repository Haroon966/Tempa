from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.jira.drafts import context_key_from_slack, load_draft
from tempa.channels.jira.tickets import handle_jira_ticket_message


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


def _ctx():
    return {
        "channel": "slack",
        "slack_user_id": "U1",
        "slack_channel_id": "C1",
        "slack_thread_ts": "111.222",
        "thread_ts": "111.222",
    }


@pytest.mark.asyncio
async def test_draft_preview_flow(ticket_env):
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

        reply1 = await handle_jira_ticket_message(
            "create ticket assign to Haroon: fix login page",
            _ctx(),
        )
        assert "preview" in reply1.lower() or "Summary" in reply1

        with patch("tempa.channels.jira.tickets.create_issue") as mock_create, patch(
            "tempa.channels.jira.tickets._check_rate_limit", return_value=True
        ):
            mock_create.return_value = {
                "status": "ok",
                "key": "ENG-42",
                "url": "https://acme.atlassian.net/browse/ENG-42",
            }
            reply2 = await handle_jira_ticket_message("yes", _ctx())
        assert "ENG-42" in reply2

    key = context_key_from_slack("C1", "111.222")
    draft = load_draft(key)
    assert draft is not None
    assert draft["state"] == "created"
    assert draft["issue_key"] == "ENG-42"


@pytest.mark.asyncio
async def test_cancel_clears_draft(ticket_env):
    with patch("tempa.channels.jira.tickets.ticket_feature_enabled", return_value=True), patch(
        "tempa.channels.jira.tickets.ensure_jira_users_fresh", new_callable=AsyncMock, return_value=None
    ), patch("tempa.channels.jira.tickets.ensure_contacts_fresh", new_callable=AsyncMock, return_value=None):
        await handle_jira_ticket_message("create ticket: something broke", _ctx())
        reply = await handle_jira_ticket_message("never mind", _ctx())
        assert "cancel" in reply.lower()


@pytest.mark.asyncio
async def test_unrelated_message_clears_preview_draft(ticket_env):
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

        preview = await handle_jira_ticket_message(
            "create ticket assign to Haroon: fix login page",
            _ctx(),
        )
        assert "preview" in preview.lower() or "Summary" in preview

        cleared = await handle_jira_ticket_message("hi", _ctx())
        assert cleared == ""
        assert load_draft(context_key_from_slack("C1", "111.222")) is None
