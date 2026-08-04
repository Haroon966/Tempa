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


def test_claude_merge_skips_coding_when_cursor_owns(monkeypatch):
    from tempa.settings import get_settings

    monkeypatch.setenv("TEMPA_COORDINATOR", "hybrid")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "tempa.channels.slack.cursor_threads.cursor_owns_coding",
        lambda: True,
    )
    assert is_coding_work_request("fix login in repo", {}) is True
    assert should_use_claude_merge("fix login in repo", {}) is False
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


def test_github_improve_ask_is_coding_work():
    """Teammate 'how can we improve this github project' → Cursor, not QA scan."""
    assert (
        is_coding_work_request(
            "https://github.com/Haroon966/Klip-Board how can we improve this project",
            {"channel": "slack"},
        )
        is True
    )


def test_raise_pr_followup_inherits_thread_repo(monkeypatch: pytest.MonkeyPatch):
    """Live failure: 'rase pr and fix it all' must not ask which issues — Cursor write."""
    monkeypatch.setattr(
        "tempa.channels.slack.cursor_threads.thread_coding_context_blob",
        lambda ctx: (
            "https://github.com/Haroon966/Klip-Board how can we improve\n"
            "CRITICAL: Exposed Google API Key"
        ),
    )
    ctx = {
        "channel": "slack",
        "slack_channel_id": "C0BDR90S9HT",
        "slack_thread_ts": "1784735182.379419",
    }
    assert is_coding_work_request("rase pr and fix it all", ctx) is True
    assert is_coding_work_request("raise PR and fix it all", ctx) is True


def test_comment_on_github_followup_is_coding_work(monkeypatch: pytest.MonkeyPatch):
    """Live failure: after a PR review, 'comment on github' must hit Cursor — not LLM clarify."""
    monkeypatch.setattr(
        "tempa.channels.slack.cursor_threads.thread_coding_context_blob",
        lambda ctx: (
            "please review this pr https://github.com/Haroon966/Jay/pull/1\n"
            "## PR Review: Approve"
        ),
    )
    ctx = {
        "channel": "slack",
        "slack_channel_id": "C0BDR90S9HT",
        "slack_thread_ts": "1785217853.773799",
    }
    assert is_coding_work_request("comment on github", ctx) is True
    assert is_coding_work_request("read comment and give final comment on pr", ctx) is True
    from tempa.channels.slack.cursor_pr import is_pr_comment_intent, is_write_intent

    assert is_pr_comment_intent("comment on github") is True
    assert is_write_intent("comment on github") is False


def test_meet_url_is_not_coding_work():
    assert is_coding_work_request(
        "please join https://meet.google.com/abc-defg-hij now",
        {"channel": "slack"},
    ) is False


def test_product_count_investigation_is_coding_work(monkeypatch: pytest.MonkeyPatch):
    """Teammate 'check if the portal count…' must go to Cursor, not QA lint."""
    monkeypatch.setattr(
        "tempa.qa.github.parse.resolve_repo_alias",
        lambda text: "Orenda-Project/compliancetracker"
        if "compliance" in (text or "").lower()
        else "",
    )
    msg = (
        "In compliance tracker, the portal teacher count in Dashboard -> "
        "School Staff seems lower. Check if the count shown is correct"
    )
    assert is_coding_work_request(msg, {"channel": "slack"}) is True


def test_product_vanish_investigation_is_coding_work(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "tempa.qa.github.parse.resolve_repo_alias",
        lambda text: "Orenda-Project/compliancetracker"
        if "compliance" in (text or "").lower()
        else "",
    )
    assert (
        is_coding_work_request(
            "In the compliance tracker, when adding a teacher that teacher vanishes — figure out what is happening",
            {"channel": "slack"},
        )
        is True
    )


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
