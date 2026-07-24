"""Tempa Cursor permanent architecture: jobs, PRs, notify, escalate."""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.slack import cursor_jobs as jobs
from tempa.channels.slack import cursor_pr as cpr
from tempa.channels.slack import cursor_qa as cqa
from tempa.channels.slack.cursor_worker import enqueue_from_slack


@pytest.fixture(autouse=True)
def _data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")
    monkeypatch.setenv("TEMPA_CURSOR_MAX_PARALLEL", "8")
    monkeypatch.setenv("TEMPA_CURSOR_CI_FIX_MAX", "3")
    monkeypatch.setenv("TEMPA_CURSOR_ESCALATE_SLACK_IDS", "U_FALLBACK")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_pr_key_parallel_users_two_keys():
    a = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    b = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U2", repo="o/r")
    assert a != b


def test_pr_key_same_user_two_threads():
    a = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    b = jobs.pr_key(channel_id="C1", thread_ts="2.2", user_id="U1", repo="o/r")
    assert a != b


def test_pr_key_same_thread_followup_same_key():
    a = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    b = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    assert a == b


def test_find_pr_binding_reuses_same_thread_user():
    key = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    jid = jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "repo": "o/r",
            "pr_key": key,
            "branch": "tempa/u1-t11",
            "pr_url": "https://github.com/o/r/pull/9",
            "pr_number": 9,
        }
    )
    jobs.update_job(jid, status="completed", phase="completed")
    binding = jobs.find_pr_binding(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    assert binding is not None
    assert binding["pr_number"] == 9
    other = jobs.find_pr_binding(channel_id="C1", thread_ts="1.1", user_id="U2", repo="o/r")
    assert other is None


def test_adopt_parse_pr_url():
    parsed = cpr.parse_pr_url("please QA https://github.com/Orenda-Project/compliancetracker/pull/492 until green")
    assert parsed is not None
    assert parsed["pr_number"] == 492
    assert parsed["full_repo"] == "Orenda-Project/compliancetracker"


def test_wants_channel_announce_only_when_asked():
    assert cpr.wants_channel_announce("fix CI and post in channel") is True
    assert cpr.wants_channel_announce("fix the failing tests") is False


def test_notify_done_surfaces_no_channel_by_default():
    posts: list[tuple] = []

    def fake_send(channel_id, text, thread_ts="", source_channel=""):
        posts.append((channel_id, text, thread_ts, source_channel))

    with (
        patch("tempa.channels.slack.outbound.send_slack_message_sync", side_effect=fake_send),
        patch("tempa.channels.slack.cursor_pr.pr_comment") as gh_comment,
        patch("tempa.channels.jira.client.add_comment") as jira_comment,
    ):
        result = cqa.notify_done(
            summary="All green on the PR.",
            channel_id="C1",
            thread_ts="1.1",
            ask_text="fix the flaky test",
            pr_number=12,
            pr_url="https://github.com/o/r/pull/12",
            repo="o/r",
            cwd=None,
            jira_key="MC20-1",
            user_id="U1",
        )

    assert result["slack_thread"] is True
    assert result["slack_channel"] is False
    assert result["github"] is True
    assert result["jira"] is True
    assert all(p[2] == "1.1" or p[3] != "cursor_job_channel" for p in posts)
    assert not any(p[3] == "cursor_job_channel" for p in posts)
    gh_comment.assert_called_once()
    jira_comment.assert_called_once_with("MC20-1", "All green on the PR.")


def test_notify_channel_when_asked():
    posts: list[tuple] = []

    def fake_send(channel_id, text, thread_ts="", source_channel=""):
        posts.append((channel_id, text, thread_ts, source_channel))

    with (
        patch("tempa.channels.slack.outbound.send_slack_message_sync", side_effect=fake_send),
        patch("tempa.channels.slack.cursor_pr.pr_comment"),
    ):
        cqa.notify_done(
            summary="Done.",
            channel_id="C1",
            thread_ts="1.1",
            ask_text="fix it and post in channel please",
            pr_number=1,
            pr_url="https://github.com/o/r/pull/1",
            repo="o/r",
            cwd=None,
            jira_key=None,
            user_id="U1",
        )

    assert any(p[3] == "cursor_job_channel" and p[2] == "" for p in posts)


def test_escalate_after_needs_help():
    posts: list[str] = []

    def fake_send(channel_id, text, thread_ts="", source_channel=""):
        posts.append(text)

    with (
        patch("tempa.channels.slack.outbound.send_slack_message_sync", side_effect=fake_send),
        patch("tempa.channels.slack.cursor_pr.pr_comment") as gh_comment,
    ):
        result = cqa.notify_done(
            summary="_Tempa needs help after 3 fix attempts on <https://github.com/o/r/pull/1>._",
            channel_id="C1",
            thread_ts="1.1",
            ask_text="fix until green",
            pr_number=1,
            pr_url="https://github.com/o/r/pull/1",
            repo="o/r",
            cwd=None,
            jira_key=None,
            user_id="U_REQ",
        )

    assert result.get("escalated") is True
    assert any("U_FALLBACK" in t for t in posts)
    assert any("U_REQ" in t for t in posts)
    gh_body = gh_comment.call_args.kwargs.get("body") or ""
    assert "needs help" in gh_body.lower()


def test_checks_summary_red_green():
    red = cpr.checks_summary(
        [{"name": "backend-ci", "state": "FAILURE"}, {"name": "frontend-ci", "state": "SUCCESS"}],
        required=["backend-ci", "frontend-ci"],
    )
    assert red["status"] == "red"
    green = cpr.checks_summary(
        [{"name": "backend-ci", "state": "SUCCESS"}, {"name": "frontend-ci", "state": "SUCCESS"}],
        required=["backend-ci", "frontend-ci"],
    )
    assert green["status"] == "green"


def test_checks_summary_skipped_is_not_green():
    skipped_only = cpr.checks_summary(
        [{"name": "backend-ci", "state": "SKIPPED"}, {"name": "lint", "state": "NEUTRAL"}],
    )
    assert skipped_only["status"] == "pending"
    assert skipped_only["passed"] == 0

    required_skipped = cpr.checks_summary(
        [{"name": "backend-ci", "state": "SKIPPED"}, {"name": "other", "state": "SUCCESS"}],
        required=["backend-ci"],
    )
    assert required_skipped["status"] == "pending"

    required_pass = cpr.checks_summary(
        [{"name": "backend-ci", "state": "SUCCESS"}, {"name": "optional", "state": "SKIPPED"}],
        required=["backend-ci"],
    )
    assert required_pass["status"] == "green"
    assert required_pass["passed"] == 1


def test_pr_head_ref_includes_lifecycle(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = (
            '{"headRefName":"fix/x","url":"https://github.com/o/r/pull/492",'
            '"number":492,"state":"MERGED","merged":true,"closedAt":"2026-07-21T00:00:00Z"}'
        )
        stderr = ""

    monkeypatch.setattr(cpr, "_run", lambda *a, **k: FakeProc())
    head = cpr.pr_head_ref(492, repo="o/r")
    assert head["branch"] == "fix/x"
    assert head["state"] == "MERGED"
    assert head["merged"] is True
    assert head["is_open"] is False
    assert cpr.is_pr_open(head) is False


def test_is_pr_open_helpers():
    assert cpr.is_pr_open({"state": "OPEN", "merged": False, "is_open": True}) is True
    assert cpr.is_pr_open({"state": "CLOSED", "merged": False, "is_open": False}) is False
    assert cpr.is_pr_open({"state": "OPEN", "merged": True}) is False
    assert cpr.is_pr_open(None) is False


def test_ensure_git_safe_directories_sets_env(tmp_path, monkeypatch):
    from tempa.channels.slack import cursor_worktree as wt

    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    monkeypatch.delenv("GIT_CONFIG_KEY_0", raising=False)
    monkeypatch.delenv("GIT_CONFIG_VALUE_0", raising=False)
    # Reset module flag so ensure runs again.
    wt._GIT_SAFE_READY = False
    repo = tmp_path / "repo"
    repo.mkdir()
    wt.ensure_git_safe_directories(repo)
    assert os.environ.get("GIT_CONFIG_VALUE_0") == "*"
    assert wt._GIT_SAFE_READY is True


def test_interrupt_stale_active_jobs():
    jid = jobs.enqueue_cursor_job({"channel_id": "C1", "thread_ts": "1.1", "user_id": "U1"})
    jobs.update_job(jid, status="running", phase="running")
    out = jobs.interrupt_stale_active_jobs()
    assert len(out) == 1
    assert jobs.get_job(jid)["status"] == "interrupted"


def test_enqueue_rejects_write_when_git_missing(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    with (
        patch("tempa.channels.slack.cursor_worktree.git_available", return_value=False),
        patch("tempa.channels.slack.cursor_pr.gh_available", return_value=True),
        patch("tempa.qa.cursor.cursor_configured", return_value=True),
    ):
        result = enqueue_from_slack(
            text="please fix the failing tests and push",
            context={
                "slack_channel_id": "C1",
                "slack_thread_ts": "1.1",
                "slack_user_id": "U1",
            },
            cfg={"local_cwd": str(repo), "repo": "o/r"},
        )
    assert "error" in result
    assert "git" in result["error"].lower()


def test_enqueue_rejects_write_when_ro(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    with (
        patch("tempa.channels.slack.cursor_worktree.git_available", return_value=True),
        patch("tempa.channels.slack.cursor_pr.gh_available", return_value=True),
        patch("tempa.qa.cursor.cursor_configured", return_value=True),
        patch("os.access", return_value=False),
    ):
        result = enqueue_from_slack(
            text="implement the fix and open a pr",
            context={
                "slack_channel_id": "C1",
                "slack_thread_ts": "1.1",
                "slack_user_id": "U1",
            },
            cfg={"local_cwd": str(repo), "repo": "o/r"},
        )
    assert "error" in result
    assert "read-only" in result["error"].lower()


def test_list_jobs_for_dashboard():
    jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "status": "running",
            "phase": "running",
            "pr_url": "https://github.com/o/r/pull/3",
        }
    )
    rows = jobs.list_jobs(limit=10)
    assert len(rows) >= 1
    assert rows[0]["user_id"] == "U1"


@pytest.mark.asyncio
async def test_cursor_jobs_api():
    from tempa.api.qa import api_cursor_jobs

    jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "phase": "running",
            "pr_url": "https://github.com/o/r/pull/3",
        }
    )
    data = await api_cursor_jobs(limit=20)
    assert any(j.get("user_id") == "U1" for j in data.get("jobs", []))


def test_jira_pin_blocks_assignee_loop(monkeypatch, tmp_path):
    from tempa.channels.jira.tickets import should_route_to_jira_ticket
    import tempa.channels.slack.cursor_threads as ct
    import yaml

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "cursor_threads.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": [],
                "threads": [
                    {
                        "channel_id": "C_PIN",
                        "thread_ts": "100.1",
                        "local_cwd": "/repos/x",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ct, "get_settings", lambda: type("S", (), {"config_dir": cfg_dir})())
    ct._cache_mtime = None
    ct._cache_threads = []
    ct._cache_repos = []
    assert (
        should_route_to_jira_ticket(
            "who should I assign this to?",
            {
                "slack_channel_id": "C_PIN",
                "slack_thread_ts": "100.1",
                "channel": "slack",
            },
        )
        is False
    )


def test_extract_jira_from_ask():
    assert cqa.extract_jira_key("see MC20-19085 and fix", None) == "MC20-19085"
    assert cqa.extract_jira_key("no ticket", "ENG-1") == "ENG-1"


@pytest.mark.asyncio
async def test_process_job_escalates_after_three_red_ci(tmp_path, monkeypatch):
    from tempa.channels.slack import cursor_worker as cw

    repo = tmp_path / "repo"
    repo.mkdir()
    key = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    jid = jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "ask_text": "fix CI until green",
            "mode": "write",
            "local_cwd": str(repo),
            "repo": "o/r",
            "pr_key": key,
            "required_checks": ["backend-ci"],
            "base_ref": "main",
        }
    )
    claimed = jobs.claim_next_jobs(1)[0]
    assert claimed["id"] == jid

    posts: list[str] = []

    async def fake_agent(job, *, comments="", ci_logs=""):
        return "agent did work"

    with (
        patch.object(cw.wt, "git_available", return_value=True),
        patch.object(cw.wt, "ensure_worktree", return_value=repo),
        patch.object(cw.wt, "remove_worktree"),
        patch.object(cw.cpr, "push_branch"),
        patch.object(
            cw.cpr,
            "create_pr",
            return_value={"pr_url": "https://github.com/o/r/pull/7", "pr_number": 7},
        ),
        patch.object(cw.cqa, "evaluate_ci", return_value={"status": "red", "failed": ["backend-ci"]}),
        patch.object(cw.cqa, "collect_comment_blockers", return_value=""),
        patch.object(cw.cpr, "failed_run_logs", return_value="boom"),
        patch.object(cw, "_run_agent", side_effect=fake_agent),
        patch.object(cw, "_post", side_effect=lambda *a, **k: posts.append(str(a))),
        patch.object(cw.cqa, "notify_done", return_value={"escalated": True}) as notify,
    ):
        await cw._process_job(claimed)

    row = jobs.get_job(jid)
    assert row["status"] == "needs_help"
    assert notify.called
    summary = notify.call_args.kwargs.get("summary") or ""
    assert "needs help" in summary.lower()


@pytest.mark.asyncio
async def test_process_job_pending_ci_times_out_to_needs_help(tmp_path, monkeypatch):
    from tempa.channels.slack import cursor_worker as cw

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("TEMPA_CURSOR_JOB_TIMEOUT_SEC", "1")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    jid = jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "ask_text": "fix until green",
            "mode": "write",
            "local_cwd": str(repo),
            "repo": "o/r",
            "required_checks": ["backend-ci"],
            "base_ref": "main",
        }
    )
    claimed = jobs.claim_next_jobs(1)[0]

    async def fake_agent(job, *, comments="", ci_logs=""):
        return "ok"

    with (
        patch.object(cw.wt, "git_available", return_value=True),
        patch.object(cw.wt, "ensure_worktree", return_value=repo),
        patch.object(cw.wt, "remove_worktree"),
        patch.object(cw.cpr, "push_branch"),
        patch.object(
            cw.cpr,
            "create_pr",
            return_value={"pr_url": "https://github.com/o/r/pull/8", "pr_number": 8},
        ),
        patch.object(cw.cqa, "evaluate_ci", return_value={"status": "pending", "pending": True}),
        patch.object(cw.cqa, "collect_comment_blockers", return_value=""),
        patch.object(cw, "_run_agent", side_effect=fake_agent),
        patch.object(cw, "_post"),
        patch.object(cw.asyncio, "sleep", new_callable=AsyncMock),
        patch.object(cw.cqa, "notify_done", return_value={}) as notify,
    ):
        # Force deadline immediately after first pending check
        real_time = time.time

        def fake_time():
            # first calls during setup, then jump past deadline
            if not hasattr(fake_time, "n"):
                fake_time.n = 0
            fake_time.n += 1
            if fake_time.n < 3:
                return real_time()
            return real_time() + 10_000

        with patch.object(cw.time, "time", side_effect=fake_time):
            await cw._process_job(claimed)

    assert jobs.get_job(jid)["status"] == "needs_help"
    kwargs = notify.call_args.kwargs
    assert "ci still pending" in (kwargs.get("summary") or "").lower()
    assert kwargs.get("escalate_only") is True


def test_missing_test_context_asks_once(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_CURSOR_TEST_ENV_FILE", str(tmp_path / "missing.env"))
    msg = cqa.missing_test_context_message(cwd=str(tmp_path), ask_text="run all tests until green")
    assert msg is not None
    assert "credentials" in msg.lower() or "missing" in msg.lower()
    assert cqa.missing_test_context_message(cwd=str(tmp_path), ask_text="what is the status?") is None


@pytest.mark.asyncio
async def test_process_job_dead_binding_opens_new_pr(tmp_path):
    from tempa.channels.slack import cursor_worker as cw

    repo = tmp_path / "repo"
    repo.mkdir()
    key = jobs.pr_key(channel_id="C1", thread_ts="1.1", user_id="U1", repo="o/r")
    old = jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "repo": "o/r",
            "pr_key": key,
            "branch": "tempa/old-492",
            "pr_url": "https://github.com/o/r/pull/492",
            "pr_number": 492,
        }
    )
    jobs.claim_next_jobs(1)  # drain queue so the follow-up job is claimed next
    jobs.update_job(old, status="completed", phase="completed")

    jid = jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "ask_text": "rase pr and fix it all",
            "mode": "write",
            "local_cwd": str(repo),
            "repo": "o/r",
            "pr_key": key,
            "required_checks": [],
            "base_ref": "main",
        }
    )
    claimed = jobs.claim_next_jobs(1)[0]
    assert claimed["id"] == jid

    async def fake_agent(job, *, comments="", ci_logs=""):
        return "fixed"

    create_calls: list[dict] = []

    def fake_create_pr(**kwargs):
        create_calls.append(kwargs)
        return {"pr_url": "https://github.com/o/r/pull/500", "pr_number": 500}

    with (
        patch.object(cw.wt, "git_available", return_value=True),
        patch.object(cw.wt, "ensure_worktree", return_value=str(repo)),
        patch.object(cw.wt, "remove_worktree"),
        patch.object(cw.wt, "branch_name", return_value="tempa/fresh-500"),
        patch.object(cw.cpr, "push_branch"),
        patch.object(cw.cpr, "create_pr", side_effect=fake_create_pr),
        patch.object(
            cw.cpr,
            "pr_head_ref",
            return_value={
                "branch": "tempa/old-492",
                "pr_number": 492,
                "pr_url": "https://github.com/o/r/pull/492",
                "state": "MERGED",
                "merged": True,
                "is_open": False,
            },
        ),
        patch.object(cw, "_run_agent", side_effect=fake_agent),
        patch.object(cw, "_post"),
        patch.object(cw.cqa, "notify_done", return_value={}) as notify,
    ):
        await cw._process_job(claimed)

    assert create_calls, "expected a new PR after dead binding"
    assert jobs.get_job(jid)["status"] == "completed"
    assert jobs.get_job(jid)["pr_number"] == 500
    summary = notify.call_args.kwargs.get("summary") or ""
    assert "492" in summary and "merged" in summary.lower()
    assert "https://github.com/o/r/pull/500" in summary
    assert "confirmed green ci" not in summary.lower()


@pytest.mark.asyncio
async def test_process_job_dead_adopt_write_opens_new_pr(tmp_path):
    from tempa.channels.slack import cursor_worker as cw

    repo = tmp_path / "repo"
    repo.mkdir()
    jid = jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "ask_text": "fix https://github.com/o/r/pull/492 and raise pr",
            "mode": "write",
            "local_cwd": str(repo),
            "repo": "o/r",
            "required_checks": [],
            "base_ref": "main",
        }
    )
    claimed = jobs.claim_next_jobs(1)[0]

    async def fake_agent(job, *, comments="", ci_logs=""):
        assert job.get("dead_pr_replaced") is True
        return "new fix"

    with (
        patch.object(cw.wt, "git_available", return_value=True),
        patch.object(cw.wt, "ensure_worktree", return_value=str(repo)) as ensure_wt,
        patch.object(cw.wt, "remove_worktree"),
        patch.object(cw.wt, "branch_name", return_value="tempa/fresh"),
        patch.object(cw.cpr, "push_branch"),
        patch.object(
            cw.cpr,
            "create_pr",
            return_value={"pr_url": "https://github.com/o/r/pull/501", "pr_number": 501},
        ) as create_pr,
        patch.object(
            cw.cpr,
            "pr_head_ref",
            return_value={
                "branch": "old-head",
                "pr_number": 492,
                "pr_url": "https://github.com/o/r/pull/492",
                "state": "MERGED",
                "merged": True,
                "is_open": False,
            },
        ),
        patch.object(cw, "_run_agent", side_effect=fake_agent),
        patch.object(cw, "_post"),
        patch.object(cw.cqa, "notify_done", return_value={}) as notify,
    ):
        await cw._process_job(claimed)

    create_pr.assert_called_once()
    # Fresh worktree from base, not the dead PR head.
    assert ensure_wt.call_args.kwargs.get("branch") == "tempa/fresh"
    summary = notify.call_args.kwargs.get("summary") or ""
    assert "opening a new pr" in summary.lower()
    assert "pull/501" in summary


@pytest.mark.asyncio
async def test_process_job_dead_adopt_suggests_without_write(tmp_path):
    from tempa.channels.slack import cursor_worker as cw

    repo = tmp_path / "repo"
    repo.mkdir()
    jid = jobs.enqueue_cursor_job(
        {
            "channel_id": "C1",
            "thread_ts": "1.1",
            "user_id": "U1",
            "ask_text": "look at https://github.com/o/r/pull/492",
            "mode": "write",  # enqueue treats PR URL as write; intent gate uses is_write_intent
            "local_cwd": str(repo),
            "repo": "o/r",
            "base_ref": "main",
        }
    )
    claimed = jobs.claim_next_jobs(1)[0]
    posts: list[str] = []

    with (
        patch.object(cw.wt, "git_available", return_value=True),
        patch.object(cw.wt, "ensure_worktree") as ensure_wt,
        patch.object(cw.cpr, "push_branch") as push,
        patch.object(cw.cpr, "create_pr") as create_pr,
        patch.object(
            cw.cpr,
            "pr_head_ref",
            return_value={
                "branch": "old-head",
                "pr_number": 492,
                "pr_url": "https://github.com/o/r/pull/492",
                "state": "MERGED",
                "merged": True,
                "is_open": False,
            },
        ),
        patch.object(cw, "_run_agent", new_callable=AsyncMock) as agent,
        patch.object(cw, "_post", side_effect=lambda *a, **k: posts.append(a[2] if len(a) > 2 else "")),
    ):
        await cw._process_job(claimed)

    assert jobs.get_job(jid)["status"] == "completed"
    assert agent.await_count == 0
    ensure_wt.assert_not_called()
    push.assert_not_called()
    create_pr.assert_not_called()
    assert posts
    assert "merged" in posts[0].lower()
    assert "new pr" in posts[0].lower()
