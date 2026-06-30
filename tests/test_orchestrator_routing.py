from __future__ import annotations

import pytest

from tempa.orchestrator.routing import is_coding_work_request, should_use_claude_merge


def test_calendar_fix_is_not_coding_work(monkeypatch):
    from tempa.settings import get_settings

    monkeypatch.setenv("TEMPA_COORDINATOR", "hybrid")
    get_settings.cache_clear()
    assert is_coding_work_request("fix my calendar tomorrow", {}) is False
    assert should_use_claude_merge("fix my calendar tomorrow", {}) is False
    get_settings.cache_clear()


def test_inbox_query_is_not_coding_work():
    assert is_coding_work_request("fix my inbox sorting", {"channel": "dashboard"}) is False


def test_repo_fix_is_coding_work():
    assert is_coding_work_request("fix login in repo", {}) is True


def test_slack_handler_fix_is_coding_work():
    assert is_coding_work_request("fix the slack reply handler", {"channel": "slack"}) is True


def test_github_url_is_coding_work():
    assert is_coding_work_request(
        "fix oauth in https://github.com/org/tempa",
        {},
    ) is True


def test_meet_url_is_not_coding_work():
    assert is_coding_work_request(
        "please join https://meet.google.com/abc-defg-hij now",
        {"channel": "slack"},
    ) is False


@pytest.mark.asyncio
async def test_varys_hook_skips_meet_url():
    from tempa.orchestrator.hooks_impl import varys_work_request_hook

    result = await varys_work_request_hook(
        "fix meet join https://meet.google.com/abc-defg-hij",
        {"channel": "slack"},
    )
    assert result is None


@pytest.mark.asyncio
async def test_varys_hook_skips_calendar_fix():
    from tempa.orchestrator.hooks_impl import varys_work_request_hook

    result = await varys_work_request_hook("fix my calendar tomorrow", {"channel": "dashboard"})
    assert result is None
