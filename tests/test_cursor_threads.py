"""Cursor-pinned Slack thread routing + Tempa job architecture."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tempa.channels.slack.context import should_handle_channel_thread
from tempa.channels.slack.cursor_threads import (
    is_cursor_thread,
    load_cursor_threads,
    match_cursor_thread,
)
from tempa.channels.slack.reply import handle_inbound_slack


@pytest.fixture(autouse=True)
def _clear_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SLACK_OWNER_USER_ID", "U_OWNER")
    monkeypatch.setenv("SLACK_ALLOW_ALL", "true")
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")
    from tempa.settings import get_settings
    import tempa.channels.slack.cursor_threads as ct

    get_settings.cache_clear()
    ct._cache_mtime = None
    ct._cache_rows = []
    yield
    get_settings.cache_clear()
    ct._cache_mtime = None
    ct._cache_rows = []


def test_match_pefsis_thread_from_config():
    cfg = match_cursor_thread("C0AV0MUTCJW", "1784541760.548649")
    assert cfg is not None
    assert cfg["local_cwd"] == "/repos/compliancetracker"
    assert cfg.get("jira_key") == "MC20-19085"
    assert is_cursor_thread("C0AV0MUTCJW", "1784541760.548649")
    # float-normalize: Slack sometimes re-serializes ts
    assert is_cursor_thread("C0AV0MUTCJW", "1784541760.5486490")
    assert not is_cursor_thread("C0AV0MUTCJW", "0.0")


def test_thread_transcript_includes_root_and_skips_users_list(monkeypatch):
    from tempa.channels.slack import cursor_threads as mod
    import tempa.channels.slack.client as slack_client

    class FakeClient:
        def conversations_replies(self, **kwargs):
            assert kwargs["channel"] == "C0AV0MUTCJW"
            return {
                "messages": [
                    {"ts": "1784541760.548649", "user": "U_ALI", "text": "teacher vanishes"},
                    {"ts": "1784541761.0", "user": "U_HAROON", "text": "fix it"},
                ]
            }

        def users_info(self, *, user):
            return {"user": {"id": user, "profile": {"display_name": user.replace("U_", "")}}}

        def users_list(self, **kwargs):
            raise AssertionError("users_list must not be called for Cursor transcripts")

    monkeypatch.setattr(slack_client, "load_slack_client", lambda: FakeClient())

    body = mod._thread_transcript(
        {"slack_channel_id": "C0AV0MUTCJW", "slack_thread_ts": "1784541760.548649"}
    )
    assert "teacher vanishes" in body
    assert "fix it" in body
    assert "ALI:" in body


def test_should_handle_cursor_thread_without_bot_history():
    event = {
        "channel": "C0AV0MUTCJW",
        "thread_ts": "1784541760.548649",
        "ts": "1784541760.548649",
        "text": "what is the status of the PR?",
        "user": "U_ALI",
    }
    assert should_handle_channel_thread(event, event["text"]) is True


@pytest.mark.asyncio
async def test_inbound_cursor_thread_skips_coordinator(monkeypatch, tmp_path):
    from tempa.channels.slack import session

    session._seen_event_ids.clear()

    say = AsyncMock()
    with (
        patch(
            "tempa.channels.slack.cursor_threads.handle_cursor_thread_message",
            new_callable=AsyncMock,
            return_value="_Tempa is working on it…_",
        ) as mock_cursor,
        patch(
            "tempa.agents.graph.run_coordinator_full",
            new_callable=AsyncMock,
        ) as mock_coord,
    ):
        result = await handle_inbound_slack(
            {
                "user": "U_RANDOM_CHANNEL_MEMBER",
                "channel": "C0AV0MUTCJW",
                "thread_ts": "1784541760.548649",
                "text": "<@UBOT> what is left to verify?",
                "ts": "1784544400.1",
            },
            event_type="app_mention",
            event_id="EvCursor1",
            say=say,
        )

    assert result["handled"] == 1
    assert result.get("cursor_thread") is True
    assert "Tempa is working" in result["reply"]
    mock_cursor.assert_awaited_once()
    mock_coord.assert_not_called()
    say.assert_awaited()


@pytest.mark.asyncio
async def test_handle_cursor_enqueues_job(monkeypatch, tmp_path):
    from tempa.channels.slack import cursor_jobs as jobs
    from tempa.channels.slack.cursor_threads import handle_cursor_thread_message
    from tempa.settings import get_settings

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    repo = tmp_path / "ct"
    repo.mkdir()
    monkeypatch.setattr(
        "tempa.channels.slack.cursor_threads.match_cursor_thread",
        lambda *a, **k: {
            "channel_id": "C0AV0MUTCJW",
            "thread_ts": "1784541760.548649",
            "local_cwd": str(repo),
            "repo": "",
            "base_ref": "main",
            "required_checks": ["backend-ci"],
            "jira_key": "MC20-19085",
            "label": "test",
        },
    )

    reply = await handle_cursor_thread_message(
        "please diagnose the flaky test",
        {
            "slack_channel_id": "C0AV0MUTCJW",
            "slack_thread_ts": "1784541760.548649",
            "slack_user_id": "U_ANYONE",
        },
    )
    assert reply is not None
    assert "Tempa is working" in reply
    rows = jobs.list_jobs()
    assert len(rows) == 1
    assert rows[0]["user_id"] == "U_ANYONE"
    assert rows[0]["status"] == "queued"
    assert rows[0]["mode"] == "read"
