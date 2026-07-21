"""Regression tests for Ali's Slack thread: update existing ticket, don't create/ask assignee."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.jira.intent import (
    wants_jira_ticket_create,
    wants_jira_ticket_edit,
    wants_jira_ticket_update,
)
from tempa.channels.jira.tickets import (
    handle_jira_ticket_message,
    should_route_to_jira_ticket,
    try_existing_ticket_update,
)


ALI_UPDATE = (
    "Use the same ticket (I have set it to In Progress), add comments for the work "
    "that needs to be done and what completed, and add reference to the PR that "
    "this work will be done on"
)

ALI_SHARE = (
    "This is the ticket on notion: "
    "https://orendatrust.atlassian.net/browse/MC20-19085 "
    "https://github.com/Orenda-Project/compliancetracker/pull/435 "
    "Apparently its fixed, but not according to requirements."
)


def test_ali_share_is_not_create():
    assert wants_jira_ticket_create(ALI_SHARE) is False
    assert should_route_to_jira_ticket(ALI_SHARE, {"channel": "slack"}) is False


def test_ali_update_is_update_not_create():
    assert wants_jira_ticket_create(ALI_UPDATE) is False
    assert wants_jira_ticket_update(ALI_UPDATE) is True
    assert wants_jira_ticket_edit(ALI_UPDATE) is True
    assert should_route_to_jira_ticket(
        ALI_UPDATE,
        {"channel": "slack", "slack_channel_id": "C1", "slack_thread_ts": "1"},
    )


@pytest.mark.asyncio
async def test_ali_update_adds_comment_and_pr_from_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    ctx = {
        "channel": "slack",
        "slack_user_id": "U1",
        "slack_channel_id": "C1",
        "slack_thread_ts": "111.222",
        "thread_ts": "111.222",
        "recent_user_messages": [ALI_SHARE],
        "conversation_messages": [
            {"role": "user", "text": ALI_SHARE},
            {
                "role": "assistant",
                "text": "PR https://github.com/Orenda-Project/compliancetracker/pull/492",
            },
        ],
    }

    with patch("tempa.channels.jira.tickets.ticket_feature_enabled", return_value=True), patch(
        "tempa.channels.jira.tickets.ensure_jira_users_fresh", new_callable=AsyncMock, return_value=None
    ), patch(
        "tempa.channels.jira.tickets.ensure_contacts_fresh", new_callable=AsyncMock, return_value=None
    ), patch("tempa.channels.jira.tickets.add_comment") as mock_comment, patch(
        "tempa.channels.jira.tickets.add_remote_link"
    ) as mock_link, patch(
        "tempa.channels.jira.tickets._fetch_slack_thread", return_value=""
    ), patch(
        "tempa.channels.jira.session.load_jira_session_config",
        return_value={"base_url": "https://orendatrust.atlassian.net"},
    ):
        mock_comment.return_value = {"status": "ok"}
        mock_link.return_value = {"status": "ok"}
        reply = await handle_jira_ticket_message(ALI_UPDATE, ctx)

    assert "MC20-19085" in reply
    assert "couldn't find that person" not in reply.lower()
    assert "multiple matches" not in reply.lower()
    mock_comment.assert_called_once()
    assert mock_comment.call_args[0][0] == "MC20-19085"
    mock_link.assert_called_once()
    assert "pull/492" in mock_link.call_args[0][1] or "pull/435" in mock_link.call_args[0][1]
    get_settings.cache_clear()


def test_try_existing_ticket_update_asks_for_key_when_missing():
    reply = try_existing_ticket_update(
        "add comments for the work that needs to be done",
        {"channel": "slack"},
        None,
    )
    assert reply is not None
    assert "which jira issue" in reply.lower()
    assert "couldn't find that person" not in reply.lower()
