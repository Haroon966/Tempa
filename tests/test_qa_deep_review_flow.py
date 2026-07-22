"""End-to-end checks for the autonomous PR deep review flow."""

import asyncio
import json

import pytest

from tempa.qa import dispatch as qa_dispatch
from tempa.qa import worker as qa_worker
from tempa.qa.job_store import claim_next_job, enqueue_scan, list_jobs
from tempa.qa.store import list_findings

PR_PAYLOAD = {
    "action": "opened",
    "pull_request": {
        "number": 7,
        "head": {"ref": "feat-branch"},
        "user": {"login": "alice"},
        "html_url": "https://github.com/o/r/pull/7",
        "title": "Add feature",
    },
    "repository": {"full_name": "o/r"},
    "installation": {"id": 5},
}


def test_pr_webhook_enqueues_deep_review(monkeypatch):
    monkeypatch.setattr(qa_dispatch, "qa_enabled", lambda: True)
    monkeypatch.setattr(
        qa_dispatch, "load_qa_config", lambda: {"scan_on_pr": True, "deep_review_on_pr": True}
    )

    qa_dispatch.handle_pull_request(PR_PAYLOAD)

    jobs = list_jobs()
    # deep_review covers the branch scan too, so it is the only job for a PR event
    assert [j["job_type"] for j in jobs] == ["deep_review"]
    review = jobs[0]
    assert review["repo"] == "o/r"
    assert review["pr_number"] == 7
    assert review["requested_by"] == "alice"
    assert review["source_channel"] == "github_webhook"
    assert review["pr_url"] == "https://github.com/o/r/pull/7"


def test_pr_webhook_skips_auto_scan_by_default(monkeypatch):
    """Opened/updated PRs must not enqueue QA unless scan_on_pr is enabled."""
    monkeypatch.setattr(qa_dispatch, "qa_enabled", lambda: True)
    monkeypatch.setattr(qa_dispatch, "load_qa_config", lambda: {})

    qa_dispatch.handle_pull_request(PR_PAYLOAD)

    assert list_jobs() == []


def test_pr_label_still_enqueues_when_auto_scan_off(monkeypatch):
    monkeypatch.setattr(qa_dispatch, "qa_enabled", lambda: True)
    monkeypatch.setattr(
        qa_dispatch,
        "load_qa_config",
        lambda: {"scan_on_pr": False, "deep_review_on_label": "tempa-deep-review"},
    )

    qa_dispatch.handle_pull_request(
        {
            **PR_PAYLOAD,
            "action": "labeled",
            "label": {"name": "tempa-deep-review"},
        }
    )

    jobs = list_jobs()
    assert [j["job_type"] for j in jobs] == ["deep_review"]
    assert jobs[0]["pr_number"] == 7


def test_worker_reviews_tests_and_comments_in_one_job(monkeypatch):
    import tempa.qa.comments as comments_mod
    import tempa.qa.deep_review.lite as lite
    import tempa.qa.github.assign as assign_mod

    def fake_gh_get(path, token):
        if path.endswith("/files"):
            return [{"filename": "app.py", "patch": "+bad = eval(x)"}]
        return {"head": {"ref": "feat-branch"}}

    async def fake_llm(prompt, *, max_tokens=4096):
        return json.dumps(
            [{"severity": "critical", "title": "eval misuse", "file": "app.py", "line": 3, "body": "b", "suggestion": "s"}]
        )

    monkeypatch.setattr(lite, "gh_get", fake_gh_get)
    monkeypatch.setattr(lite, "get_github_token", lambda repo: "tok")
    monkeypatch.setattr(lite, "github_uses_pat", lambda: True)
    monkeypatch.setattr(lite, "deep_review_complete", fake_llm)
    monkeypatch.setattr(
        assign_mod,
        "ensure_pr_assignee",
        lambda repo, pr: {"status": "assigned", "assignee": "alice", "reason": "pr_author"},
    )

    scanned = {}

    def fake_scan_branch(repo, branch, *, installation_id=None, scan_job_id=""):
        scanned.update(repo=repo, branch=branch, scan_job_id=scan_job_id)
        return {
            "repo": repo,
            "branch": branch,
            "grade": "B",
            "finding_count": 0,
            "branch_status": {"branch": branch, "grade": "B", "ci_status": "success",
                              "lint_status": "success", "test_status": "success", "security_count": 0},
        }

    monkeypatch.setattr(qa_worker, "scan_branch", fake_scan_branch)

    posted = {}

    def fake_post_summary(repo, pr_number, findings, *, branch_status=None):
        posted.update(repo=repo, pr_number=pr_number, findings=findings, branch_status=branch_status)
        return {"status": "posted", "url": "https://github.com/o/r/pull/7#comment-1"}

    monkeypatch.setattr(comments_mod, "post_review_summary", fake_post_summary)
    monkeypatch.setattr(qa_worker, "load_qa_config", lambda: {"auto_comment_on_pr": True})

    job_id = enqueue_scan(
        "o/r",
        pr_number=7,
        job_type="deep_review",
        priority=True,
        extra={"requested_by": "+923001112233", "source_channel": "whatsapp"},
    )
    job = claim_next_job()
    assert job and job["id"] == job_id

    asyncio.run(qa_worker._process_job(job))

    findings = list_findings(scan_job_id=job_id, status=None)
    assert len(findings) == 1 and findings[0]["severity"] == "critical"

    # tested (branch scan ran in the same job) and commented (with branch status)
    assert scanned["branch"] == "feat-branch" and scanned["scan_job_id"] == job_id
    assert posted["pr_number"] == 7 and len(posted["findings"]) == 1
    assert posted["branch_status"]["grade"] == "B"

    done = next(j for j in list_jobs() if j["id"] == job_id)
    assert done["status"] == "completed"
    assert done["result"]["comment_url"].endswith("#comment-1")
    assert done["result"]["grade"] == "B"
    assert done["result"]["assign"]["status"] == "assigned"


def test_ensure_pr_assignee_skips_when_already_assigned(monkeypatch):
    import tempa.qa.github.assign as assign_mod

    monkeypatch.setattr(assign_mod, "get_github_token", lambda repo: "tok")
    monkeypatch.setattr(
        assign_mod,
        "gh_get",
        lambda path, token: {"user": {"login": "alice"}, "assignees": [{"login": "bob"}]},
    )
    posted = {}

    def fake_post(path, token, data):
        posted.update(path=path, data=data)
        return {"assignees": data["assignees"]}

    monkeypatch.setattr(assign_mod, "gh_post", fake_post)
    result = assign_mod.ensure_pr_assignee("o/r", 7)
    assert result["status"] == "already_assigned"
    assert result["assignees"] == ["bob"]
    assert not posted


def test_ensure_pr_assignee_uses_first_human_comment(monkeypatch):
    import tempa.qa.github.assign as assign_mod

    monkeypatch.setattr(assign_mod, "get_github_token", lambda repo: "tok")

    def fake_get(path, token):
        if "/pulls/" in path:
            return {"user": {"login": "alice"}, "assignees": []}
        return [
            {"user": {"login": "dependabot[bot]"}, "body": "bump"},
            {"user": {"login": "Haroon966"}, "body": "## Tempa QA — Deep review"},
            {"user": {"login": "reviewer1"}, "body": "LGTM with nits"},
        ]

    monkeypatch.setattr(assign_mod, "gh_get", fake_get)
    posted = {}

    def fake_post(path, token, data):
        posted.update(path=path, data=data)
        return {"assignees": [{"login": data["assignees"][0]}]}

    monkeypatch.setattr(assign_mod, "gh_post", fake_post)
    result = assign_mod.ensure_pr_assignee("o/r", 7)
    assert result["status"] == "assigned"
    assert result["assignee"] == "reviewer1"
    assert result["reason"] == "first_comment"
    assert posted["data"] == {"assignees": ["reviewer1"]}


def test_ensure_pr_assignee_falls_back_to_author(monkeypatch):
    import tempa.qa.github.assign as assign_mod

    monkeypatch.setattr(assign_mod, "get_github_token", lambda repo: "tok")

    def fake_get(path, token):
        if "/pulls/" in path:
            return {"user": {"login": "alice"}, "assignees": []}
        return []

    monkeypatch.setattr(assign_mod, "gh_get", fake_get)
    monkeypatch.setattr(
        assign_mod,
        "gh_post",
        lambda path, token, data: {"assignees": [{"login": data["assignees"][0]}]},
    )
    result = assign_mod.ensure_pr_assignee("o/r", 7)
    assert result["status"] == "assigned"
    assert result["assignee"] == "alice"
    assert result["reason"] == "pr_author"


def test_qa_hook_routes_pr_link_from_chat(monkeypatch):
    import tempa.qa.config as qa_config
    import tempa.qa.scan_request as scan_request
    from tempa.orchestrator.hooks_impl import qa_scan_hook

    monkeypatch.setattr(qa_config, "qa_enabled", lambda: True)
    monkeypatch.setattr(scan_request, "github_configured", lambda: True)
    monkeypatch.setattr(scan_request, "github_uses_pat", lambda: False)
    monkeypatch.setattr(scan_request, "installation_id_for_repo", lambda repo: 5)

    result = asyncio.run(
        qa_scan_hook(
            "github.com/o/r/pull/479 please review this pr and comment on it",
            {
                "channel": "slack",
                "slack_user_id": "U123",
                "slack_privileged": True,
                "slack_channel_id": "C_TEAM",
                "slack_thread_ts": "111.222",
            },
        )
    )
    assert result is not None
    assert "queued a priority review" in result["response"]
    assert "comment on the PR" in result["response"]
    assert "report back here" in result["response"]
    assert "assign" in result["response"].lower()
    assert "PR #479" in result["response"]

    job = claim_next_job()
    assert job["job_type"] == "deep_review"
    assert job["pr_number"] == 479
    assert job["requested_by"] == "U123"
    assert job["slack_channel_id"] == "C_TEAM"
    assert job["slack_thread_ts"] == "111.222"

    # No PR link -> hook stays out of the way
    assert asyncio.run(qa_scan_hook("what meetings do I have today?", {})) is None


@pytest.mark.asyncio
async def test_worker_comments_and_reports_slack_for_user_qa(monkeypatch):
    import tempa.qa.comments as comments_mod
    import tempa.qa.deep_review.lite as lite
    import tempa.qa.github.assign as assign_mod
    import tempa.qa.notify as qa_notify

    def fake_gh_get(path, token):
        if path.endswith("/files"):
            return [{"filename": "app.py", "patch": "+x = 1"}]
        return {"head": {"ref": "feat"}}

    async def fake_llm(prompt, *, max_tokens=4096):
        return "[]"

    monkeypatch.setattr(lite, "gh_get", fake_gh_get)
    monkeypatch.setattr(lite, "get_github_token", lambda repo: "tok")
    monkeypatch.setattr(lite, "github_uses_pat", lambda: True)
    monkeypatch.setattr(lite, "deep_review_complete", fake_llm)
    monkeypatch.setattr(
        assign_mod,
        "ensure_pr_assignee",
        lambda repo, pr: {"status": "assigned", "assignee": "alice", "reason": "pr_author"},
    )
    monkeypatch.setattr(
        qa_worker,
        "scan_branch",
        lambda *a, **k: {
            "grade": "A",
            "finding_count": 0,
            "branch_status": {
                "branch": "feat",
                "grade": "A",
                "ci_status": "success",
                "lint_status": "success",
                "test_status": "success",
                "security_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        comments_mod,
        "post_review_summary",
        lambda *a, **k: {"status": "posted", "url": "https://github.com/o/r/pull/9#comment-1"},
    )
    monkeypatch.setattr(qa_worker, "load_qa_config", lambda: {"auto_comment_on_pr": False})

    posted = {}

    def fake_slack(channel, text, *, thread_ts="", source_channel=""):
        posted.update(channel=channel, text=text, thread_ts=thread_ts, source_channel=source_channel)
        return {"status": "sent"}

    monkeypatch.setattr(qa_notify, "send_slack_message_sync", fake_slack, raising=False)
    monkeypatch.setattr(
        "tempa.channels.slack.outbound.send_slack_message_sync",
        fake_slack,
    )

    job_id = enqueue_scan(
        "o/r",
        pr_number=9,
        job_type="deep_review",
        priority=True,
        extra={
            "requested_by": "U1",
            "source_channel": "slack",
            "slack_channel_id": "C1",
            "slack_thread_ts": "1.2",
        },
    )
    job = claim_next_job()
    assert job and job["id"] == job_id
    await qa_worker._process_job(job)

    done = next(j for j in list_jobs() if j["id"] == job_id)
    assert done["status"] == "completed"
    assert done["result"]["comment_url"].endswith("#comment-1")
    assert posted["channel"] == "C1"
    assert posted["thread_ts"] == "1.2"
    assert "QA results" in posted["text"] or "o/r" in posted["text"]
    assert "comment-1" in posted["text"]


def test_notify_skips_github_webhook_jobs():
    from tempa.qa.notify import user_requested_qa

    assert user_requested_qa({"source_channel": "slack"}) is True
    assert user_requested_qa({"source_channel": "github_webhook"}) is False
    assert user_requested_qa({"source_channel": "scheduler"}) is False


def test_qa_hook_ignores_product_check_phrasing(monkeypatch):
    """'Check if the portal teacher count…' is support, not a lint/security scan."""
    import tempa.qa.config as qa_config
    from tempa.orchestrator.hooks_impl import qa_scan_hook
    from tempa.qa.allowed_repos import add_repo, remove_repo

    monkeypatch.setattr(qa_config, "qa_enabled", lambda: True)
    add_repo("Orenda-Project/compliancetracker", source="test")
    try:
        msg = (
            "In compliance tracker, the portal teacher count in Dashboard -> "
            "School Staff seems to be lower than expected. Right now it shows "
            "128 Portal Teachers, but it should be higher. Check if the count "
            "shown on the Dashboard is the actual, correct count"
        )
        assert asyncio.run(qa_scan_hook(msg, {"channel": "slack"})) is None
    finally:
        remove_repo("Orenda-Project/compliancetracker")


def test_qa_hook_routes_repo_main_branch_from_chat(monkeypatch):
    """Dashboard 'review this main github.com/owner/repo main branch' must not ask for tokens."""
    import tempa.qa.config as qa_config
    import tempa.qa.scan_request as scan_request
    from tempa.orchestrator.hooks_impl import qa_scan_hook
    from tempa.qa.job_store import claim_next_job

    monkeypatch.setattr(qa_config, "qa_enabled", lambda: True)
    monkeypatch.setattr(scan_request, "github_configured", lambda: True)
    monkeypatch.setattr(scan_request, "github_uses_pat", lambda: True)
    monkeypatch.setattr(scan_request, "repo_is_allowed", lambda repo: True)
    monkeypatch.setattr(scan_request, "installation_id_for_repo", lambda repo: None)

    msg = "review and test this main github.com/AliAhmed-004/gaming-adda main branch completly"
    result = asyncio.run(qa_scan_hook(msg, {"channel": "dashboard"}))
    assert result is not None
    assert "credential" not in result["response"].lower()
    assert "token" not in result["response"].lower()
    assert "AliAhmed-004/gaming-adda" in result["response"]
    assert "main" in result["response"]
    assert "queued" in result["response"].lower()

    job = claim_next_job()
    assert job["job_type"] == "branch_scan"
    assert job["repo"] == "AliAhmed-004/gaming-adda"
    assert job["branch"] == "main"


def test_sanitize_missing_info_strips_credential_asks():
    from tempa.orchestrator.understand import _sanitize_missing_info

    cleaned = _sanitize_missing_info(
        [
            "GitHub authentication credentials or token to access the repo",
            "specific focus areas for the review",
        ]
    )
    assert cleaned == ["specific focus areas for the review"]


def test_chat_pr_link_jumps_queue_with_metadata(monkeypatch):
    import tempa.qa.config as qa_config
    import tempa.qa.scan_request as scan_request

    monkeypatch.setattr(qa_config, "qa_enabled", lambda: True)
    monkeypatch.setattr(scan_request, "github_configured", lambda: True)
    monkeypatch.setattr(scan_request, "github_uses_pat", lambda: False)
    monkeypatch.setattr(scan_request, "installation_id_for_repo", lambda repo: 5)

    enqueue_scan("other/repo", job_type="repo_scan")  # scheduled background job already waiting

    result = scan_request.handle_github_scan_request(
        "please review https://github.com/o/r/pull/7 asap",
        source_channel="whatsapp",
        requested_by="+923001112233",
    )
    assert result["status"] == "queued"
    assert result["pr_number"] == 7
    assert result["priority"] is True

    first = claim_next_job()
    assert first["job_type"] == "deep_review"
    assert first["repo"] == "o/r"
    assert first["requested_by"] == "+923001112233"
    assert first["source_channel"] == "whatsapp"
    assert "review" in first["request_message"]
    assert first["pr_url"] == "https://github.com/o/r/pull/7"


@pytest.mark.asyncio
async def test_deep_review_prefers_cursor_then_falls_back(monkeypatch):
    from tempa.qa.llm import deep_review_complete

    async def fake_cursor(**kwargs):
        return '[{"severity": "suggestion", "title": "from cursor"}]'

    monkeypatch.setattr("tempa.qa.cursor.cursor_configured", lambda: True)
    monkeypatch.setattr("tempa.qa.cursor.cursor_complete", fake_cursor)
    assert "from cursor" in await deep_review_complete("review this pr")

    async def fake_groq(messages, *, max_tokens=2048):
        return '{"findings": []}'

    monkeypatch.setattr("tempa.qa.cursor.cursor_configured", lambda: False)
    monkeypatch.setattr("tempa.qa.claude.claude_configured", lambda: False)
    monkeypatch.setattr("tempa.qa.llm.groq_complete", fake_groq)
    assert "findings" in await deep_review_complete("review this pr")


def test_wants_qa_results_followup():
    from tempa.qa.github.parse import wants_qa_results

    assert wants_qa_results("any error or bugs you found")
    assert wants_qa_results("what findings did you get?")
    assert not wants_qa_results("do QA of this repo github.com/a/b")


def test_qa_results_hook_uses_conversation_repo(monkeypatch, tmp_path):
    import tempa.qa.config as qa_config
    import tempa.qa.results_reply as reply
    from tempa.orchestrator.hooks_impl import qa_results_hook

    monkeypatch.setattr(qa_config, "qa_enabled", lambda: True)
    monkeypatch.setattr(reply, "list_branch_statuses", lambda repo=None: [
        {"branch": "main", "grade": "A", "ci_status": "success",
         "lint_status": "success", "test_status": "success", "security_count": 0}
    ])
    monkeypatch.setattr(reply, "list_findings", lambda **kwargs: [])
    monkeypatch.setattr(reply, "list_jobs", lambda limit=50: [])

    result = asyncio.run(
        qa_results_hook(
            "any error or bugs you found",
            {"recent_user_messages": ["github.com/Haroon966/WISP do QA of this repo."]},
        )
    )
    assert result is not None
    assert "Haroon966/WISP" in result["response"]
    assert "No open findings" in result["response"]
