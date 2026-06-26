from __future__ import annotations

from unittest.mock import patch

import pytest

from tempa.core.pending_actions import create_pending_action, execute_pending_action


@pytest.fixture
def pending_store(tmp_path, monkeypatch):
    store = tmp_path / "pending_actions.json"
    monkeypatch.setattr("tempa.core.pending_actions._store_path", lambda: store)
    yield store


@pytest.mark.asyncio
async def test_jira_create_issue_pending_action_executes(pending_store):
    action = create_pending_action(
        "jira_create_issue",
        {
            "project": "ENG",
            "summary": "Fix OAuth redirect",
            "description": "Update callback URL",
            "issue_type": "Task",
        },
        source_channel="dashboard",
    )

    with patch("tempa.channels.jira.client.create_issue") as mock_create:
        mock_create.return_value = {"status": "ok", "key": "ENG-42", "url": "https://x/browse/ENG-42"}
        result = await execute_pending_action(action["id"])

    assert result["status"] == "executed"
    assert result["result"]["key"] == "ENG-42"
    mock_create.assert_called_once_with(
        project="ENG",
        summary="Fix OAuth redirect",
        description="Update callback URL",
        issue_type="Task",
    )


@pytest.mark.asyncio
async def test_jira_comment_pending_action_executes(pending_store):
    action = create_pending_action(
        "jira_comment",
        {"issue_key": "ENG-1", "body": "Shipped in PR #99"},
        source_channel="dashboard",
    )

    with patch("tempa.channels.jira.client.add_comment") as mock_comment:
        mock_comment.return_value = {"status": "ok", "comment_id": "100", "issue_key": "ENG-1"}
        result = await execute_pending_action(action["id"])

    assert result["status"] == "executed"
    mock_comment.assert_called_once_with("ENG-1", "Shipped in PR #99")
