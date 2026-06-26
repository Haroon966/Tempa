from __future__ import annotations

from unittest.mock import patch

import pytest

from tempa.agents.specialists import _slack_read_query_from_context
from tempa.channels.jira.direct_reply import try_jira_direct_reply
from tempa.channels.slack.direct_reply import try_slack_direct_reply


@pytest.mark.asyncio
async def test_jira_list_projects_direct_reply():
    projects = [{"key": "ENG", "name": "Engineering"}, {"key": "OPS", "name": "Operations"}]
    with patch("tempa.channels.jira.client.jira_configured", return_value=True):
        with patch("tempa.channels.jira.client.list_projects", return_value=projects):
            reply = await try_jira_direct_reply("List my Jira projects")

    assert reply is not None
    assert "ENG" in reply
    assert "Engineering" in reply


@pytest.mark.asyncio
async def test_slack_direct_reply_skips_jira_request():
    ctx = {"channel": "slack", "inbound_slack": True, "slack_channel_id": "D123"}
    with patch("tempa.agents.specialists.run_channel_agent") as mock_channel:
        reply = await try_slack_direct_reply("List my Jira projects", ctx)
    assert reply is None
    mock_channel.assert_not_called()


def test_slack_read_query_does_not_inherit_prior_for_jira(monkeypatch):
    monkeypatch.setattr(
        "tempa.agents.specialists.get_slack_recent_messages",
        lambda *args, **kwargs: [
            {
                "role": "user",
                "text": "check latest message from varys in regionpunjab-internal channel",
            }
        ],
    )
    query = _slack_read_query_from_context(
        "List my Jira projects",
        {"slack_channel_id": "D123", "slack_thread_ts": "1.0"},
    )
    assert query == "List my Jira projects"
    assert "varys" not in query.lower()
