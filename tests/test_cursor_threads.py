"""Cursor Slack coding routing + Tempa job architecture."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import yaml

from tempa.channels.slack.context import should_handle_channel_thread
from tempa.channels.slack.cursor_threads import (
    is_cursor_thread,
    match_cursor_repo,
    match_cursor_thread,
)
from tempa.channels.slack.reply import handle_inbound_slack

SAMPLE_CFG = {
    "repos": [
        {
            "id": "demo-app",
            "local_cwd": "/repos/demo-app",
            "repo": "org/demo-app",
            "base_ref": "main",
            "required_checks": ["ci"],
            "aliases": ["demo", "demo-app"],
        }
    ],
    "threads": [
        {
            "channel_id": "C_PIN",
            "thread_ts": "100.1",
            "local_cwd": "/repos/demo-app",
            "repo": "org/demo-app",
            "base_ref": "main",
            "required_checks": ["ci"],
            "jira_key": "ENG-1",
            "label": "demo pin",
        }
    ],
}


@pytest.fixture(autouse=True)
def _cursor_cfg(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SLACK_OWNER_USER_ID", "U_OWNER")
    monkeypatch.setenv("SLACK_ALLOW_ALL", "false")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U_OWNER,U_DEV")
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "cursor_threads.yaml").write_text(
        yaml.safe_dump(SAMPLE_CFG), encoding="utf-8"
    )

    from tempa.settings import get_settings
    import tempa.channels.slack.cursor_threads as ct

    get_settings.cache_clear()
    monkeypatch.setattr(ct, "get_settings", lambda: type("S", (), {"config_dir": cfg_dir})())
    ct._cache_mtime = None
    ct._cache_threads = []
    ct._cache_repos = []
    yield
    get_settings.cache_clear()
    ct._cache_mtime = None
    ct._cache_threads = []
    ct._cache_repos = []


def test_match_pin_and_repo_from_config():
    cfg = match_cursor_thread("C_PIN", "100.1")
    assert cfg is not None
    assert cfg["local_cwd"] == "/repos/demo-app"
    assert cfg.get("jira_key") == "ENG-1"
    assert is_cursor_thread("C_PIN", "100.1")
    assert is_cursor_thread("C_PIN", "100.10")
    assert not is_cursor_thread("C_PIN", "0.0")
    assert match_cursor_repo("please fix demo-app login")["id"] == "demo-app"


def test_thread_transcript_includes_root_and_skips_users_list(monkeypatch):
    from tempa.channels.slack import cursor_threads as mod
    import tempa.channels.slack.client as slack_client

    class FakeClient:
        def conversations_replies(self, **kwargs):
            assert kwargs["channel"] == "C_PIN"
            return {
                "messages": [
                    {"ts": "100.1", "user": "U_ALI", "text": "teacher vanishes"},
                    {"ts": "100.2", "user": "U_HAROON", "text": "fix it"},
                ]
            }

        def users_info(self, *, user):
            return {"user": {"id": user, "profile": {"display_name": user.replace("U_", "")}}}

        def users_list(self, **kwargs):
            raise AssertionError("users_list must not be called for Cursor transcripts")

    monkeypatch.setattr(slack_client, "load_slack_client", lambda: FakeClient())

    body = mod._thread_transcript({"slack_channel_id": "C_PIN", "slack_thread_ts": "100.1"})
    assert "teacher vanishes" in body
    assert "fix it" in body
    assert "ALI:" in body


def test_should_handle_cursor_thread_without_bot_history():
    event = {
        "channel": "C_PIN",
        "thread_ts": "100.1",
        "ts": "100.1",
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
            "tempa.channels.slack.cursor_threads.handle_cursor_job_message",
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
                "user": "U_DEV",
                "channel": "C_PIN",
                "thread_ts": "100.1",
                "text": "<@UBOT> what is left to verify?",
                "ts": "100.2",
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
async def test_guest_coding_denied(monkeypatch, tmp_path):
    from tempa.channels.slack import session
    from tempa.channels.slack.messages import GUEST_CODING_DENIED

    session._seen_event_ids.clear()
    say = AsyncMock()
    with (
        patch(
            "tempa.channels.slack.cursor_threads.handle_cursor_job_message",
            new_callable=AsyncMock,
        ) as mock_cursor,
        patch(
            "tempa.agents.graph.run_coordinator_full",
            new_callable=AsyncMock,
        ) as mock_coord,
    ):
        result = await handle_inbound_slack(
            {
                "user": "U_GUEST",
                "channel": "C_OTHER",
                "thread_ts": "200.1",
                "text": "<@UBOT> fix the flaky login test in demo-app",
                "ts": "200.2",
            },
            event_type="app_mention",
            event_id="EvGuestCoding",
            say=say,
        )

    assert result["handled"] == 1
    assert result.get("cursor_denied") is True
    assert result["reply"] == GUEST_CODING_DENIED
    mock_cursor.assert_not_called()
    mock_coord.assert_not_called()


@pytest.mark.asyncio
async def test_inbound_coding_ask_routes_to_cursor_without_pin(monkeypatch, tmp_path):
    from tempa.channels.slack import session

    session._seen_event_ids.clear()
    repo = tmp_path / "demo-app"
    repo.mkdir()

    say = AsyncMock()
    with (
        patch(
            "tempa.channels.slack.cursor_threads.cursor_owns_coding",
            return_value=True,
        ),
        patch(
            "tempa.channels.slack.cursor_threads.resolve_cursor_job_cfg",
            return_value={
                "local_cwd": str(repo),
                "repo": "org/demo-app",
                "base_ref": "main",
                "required_checks": ["ci"],
            },
        ),
        patch(
            "tempa.channels.slack.cursor_threads.handle_cursor_job_message",
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
                "user": "U_DEV",
                "channel": "C_OTHER",
                "thread_ts": "300.1",
                "text": "<@UBOT> fix the flaky login test in demo-app",
                "ts": "300.2",
            },
            event_type="app_mention",
            event_id="EvCursorCoding1",
            say=say,
        )

    assert result["handled"] == 1
    assert result.get("cursor_coding") is True
    assert result.get("cursor_thread") is False
    mock_cursor.assert_awaited_once()
    mock_coord.assert_not_called()


def test_match_cursor_repo_by_alias():
    cfg = match_cursor_repo("please fix the vanish bug in demo")
    assert cfg is not None
    assert cfg["local_cwd"] == "/repos/demo-app"


def test_match_cursor_repo_by_github_url():
    cfg = match_cursor_repo("fix oauth in https://github.com/org/demo-app")
    assert cfg is not None
    assert "demo-app" in cfg["local_cwd"]


def test_match_cursor_repo_cloud_fallback_for_unmounted_github():
    """Unmounted github.com/owner/repo → Cursor cloud cfg (empty local_cwd)."""
    cfg = match_cursor_repo(
        "https://github.com/Haroon966/Klip-Board how can we improve this project"
    )
    assert cfg is not None
    assert cfg["repo"] == "Haroon966/Klip-Board"
    assert cfg["local_cwd"] == ""


def test_github_url_with_trailing_spaces_not_stolen_by_ct_alias():
    """Live failure: alias `ct` matched inside `project` and stole Klip-Board onto CT mount."""
    cfg = match_cursor_repo(
        "https://github.com/Haroon966/Klip-Board   how can we improve this project",
        allow_sole_default=False,
    )
    assert cfg is not None
    assert cfg["repo"] == "Haroon966/Klip-Board"
    assert cfg["local_cwd"] == ""


def test_alias_ct_does_not_match_project_word():
    from tempa.channels.slack.cursor_threads import _alias_in_text

    assert _alias_in_text("ct", "how can we improve this project") is False
    assert _alias_in_text("ct", "please fix ct login") is True
    assert _alias_in_text("compliance tracker", "in compliance tracker check count") is True


def test_resolve_cfg_inherits_repo_from_thread_history(monkeypatch):
    from tempa.channels.slack.cursor_threads import resolve_cursor_job_cfg

    monkeypatch.setattr(
        "tempa.channels.slack.cursor_threads.thread_coding_context_blob",
        lambda ctx: "https://github.com/Haroon966/Klip-Board improve this\nCRITICAL key",
    )
    cfg = resolve_cursor_job_cfg(
        "rase pr and fix it all",
        channel_id="C_THREAD",
        thread_ts="400.1",
    )
    assert cfg is not None
    assert cfg["repo"] == "Haroon966/Klip-Board"
    assert cfg["local_cwd"] == ""


def test_raise_pr_typo_is_write_intent():
    from tempa.channels.slack.cursor_pr import is_write_intent

    assert is_write_intent("rase pr and fix it all") is True
    assert is_write_intent("raise PR and fix them all") is True


@pytest.mark.asyncio
async def test_github_improve_routes_to_cursor_not_coordinator(tmp_path):
    from tempa.channels.slack import session

    session._seen_event_ids.clear()
    say = AsyncMock()
    with (
        patch(
            "tempa.channels.slack.cursor_threads.cursor_owns_coding",
            return_value=True,
        ),
        patch(
            "tempa.channels.slack.cursor_threads.resolve_cursor_job_cfg",
            return_value={
                "local_cwd": "",
                "repo": "Haroon966/Klip-Board",
                "base_ref": "main",
                "required_checks": [],
            },
        ),
        patch(
            "tempa.channels.slack.cursor_threads.handle_cursor_job_message",
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
                "user": "U_DEV",
                "channel": "C_OTHER",
                "thread_ts": "400.1",
                "text": (
                    "<@UBOT> https://github.com/Haroon966/Klip-Board "
                    "how can we improve this project"
                ),
                "ts": "400.2",
            },
            event_type="app_mention",
            event_id="EvGithubImprove1",
            say=say,
        )

    assert result["handled"] == 1
    assert result.get("cursor_coding") is True
    mock_cursor.assert_awaited_once()
    mock_coord.assert_not_called()


@pytest.mark.asyncio
async def test_raise_pr_followup_routes_to_cursor_not_clarifier(tmp_path):
    """Live Slack failure: after QA findings, 'rase pr and fix it all' must hit Cursor."""
    from tempa.channels.slack import session

    session._seen_event_ids.clear()
    say = AsyncMock()
    with (
        patch(
            "tempa.channels.slack.cursor_threads.cursor_owns_coding",
            return_value=True,
        ),
        patch(
            "tempa.channels.slack.cursor_threads.thread_coding_context_blob",
            return_value=(
                "https://github.com/Haroon966/Klip-Board how can we improve\n"
                "CRITICAL: Exposed Google API Key"
            ),
        ),
        patch(
            "tempa.channels.slack.cursor_threads.resolve_cursor_job_cfg",
            return_value={
                "local_cwd": "",
                "repo": "Haroon966/Klip-Board",
                "base_ref": "main",
                "required_checks": [],
            },
        ),
        patch(
            "tempa.channels.slack.cursor_threads.handle_cursor_job_message",
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
                "user": "U_DEV",
                "channel": "C_OTHER",
                "thread_ts": "400.1",
                "text": "<@UBOT> rase pr and fix it all",
                "ts": "400.9",
            },
            event_type="app_mention",
            event_id="EvRaisePrFollowup1",
            say=say,
        )

    assert result["handled"] == 1
    assert result.get("cursor_coding") is True
    mock_cursor.assert_awaited_once()
    mock_coord.assert_not_called()


def test_empty_shipped_template_loads():
    from tempa.settings import get_settings
    import tempa.channels.slack.cursor_threads as ct

    # Example template is the safe starter; live yaml may have mounts.
    example = get_settings().project_root / "config" / "cursor_threads.yaml.example"
    assert example.exists()
    data = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
    assert isinstance(data, dict)
    assert "repos" in data or "threads" in data
    _ = ct  # module import smoke


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
            "channel_id": "C_PIN",
            "thread_ts": "100.1",
            "local_cwd": str(repo),
            "repo": "",
            "base_ref": "main",
            "required_checks": ["ci"],
            "jira_key": "ENG-1",
            "label": "test",
        },
    )

    reply = await handle_cursor_thread_message(
        "please diagnose the flaky test",
        {
            "slack_channel_id": "C_PIN",
            "slack_thread_ts": "100.1",
            "slack_user_id": "U_DEV",
        },
    )
    assert reply is not None
    assert "working" in reply.lower() or "on it" in reply.lower()
    rows = jobs.list_jobs()
    assert len(rows) == 1
    assert rows[0]["user_id"] == "U_DEV"
    assert rows[0]["status"] == "queued"
    assert rows[0]["mode"] == "read"
