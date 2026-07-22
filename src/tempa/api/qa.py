"""QA API routes."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tempa.qa.comments import post_finding_comment
from tempa.qa.config import qa_enabled
from tempa.qa.dispatch import dispatch_event
from tempa.qa.github.auth import github_auth_mode, github_configured
from tempa.qa.job_store import list_jobs
from tempa.qa.store import get_finding, list_branch_statuses, list_findings, summary_stats
from tempa.qa.webhook import verify_webhook_request, webhook_configured

logger = logging.getLogger(__name__)

router = APIRouter()


class RepoRequest(BaseModel):
    repo: str


class ScanRequest(BaseModel):
    repo: str
    branch: str | None = None
    pr_number: int | None = None


class DeepReviewRequest(BaseModel):
    pr_url: str = ""
    repo: str = ""
    pr_number: int = 0


@router.post("/github/webhook")
async def github_webhook(request: Request):
    if not webhook_configured():
        raise HTTPException(status_code=503, detail="webhook_not_configured")
    payload_bytes = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    client_ip = (
        request.headers.get("X-Forwarded-For", request.client.host if request.client else "")
        .split(",")[0]
        .strip()
    )
    ok, err = verify_webhook_request(payload_bytes=payload_bytes, headers=headers, client_ip=client_ip)
    if not ok:
        raise HTTPException(status_code=401, detail=err)

    event = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    dispatch_event(event, payload)
    return JSONResponse({"status": "accepted"}, status_code=202)


@router.get("/qa/summary")
async def api_qa_summary():
    from tempa.settings import get_settings

    settings = get_settings()
    groq_ok = bool(settings.load_groq_api_key())
    gh_ok = github_configured()
    auth_mode = github_auth_mode()
    if not qa_enabled():
        return {
            "enabled": False,
            "configured": gh_ok,
            "groq_configured": groq_ok,
            "github_configured": gh_ok,
            "github_auth_mode": auth_mode,
        }
    return {
        "enabled": True,
        "configured": gh_ok,
        "groq_configured": groq_ok,
        "github_configured": gh_ok,
        "github_auth_mode": auth_mode,
        "qa_engine": "groq",
        **summary_stats(),
    }


@router.get("/qa/branches")
async def api_qa_branches(repo: str | None = None):
    return {"branches": list_branch_statuses(repo=repo)}


@router.get("/qa/findings")
async def api_qa_findings(
    repo: str | None = None,
    branch: str | None = None,
    status: str | None = "open",
    scan_job_id: str | None = None,
    limit: int = 100,
):
    return {
        "findings": list_findings(
            repo=repo, branch=branch, status=status, scan_job_id=scan_job_id, limit=limit
        )
    }


@router.get("/qa/jobs")
async def api_qa_jobs(limit: int = 50):
    return {"jobs": list_jobs(limit=limit)}


@router.get("/cursor/jobs")
async def api_cursor_jobs(limit: int = 50):
    from tempa.channels.slack import cursor_jobs as cursor_job_store

    return {"jobs": cursor_job_store.list_jobs(limit=limit)}


@router.get("/cursor/jobs/{job_id}")
async def api_cursor_job(job_id: str):
    from tempa.channels.slack import cursor_jobs as cursor_job_store

    job = cursor_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"job": job}


@router.get("/cursor/sessions")
async def api_cursor_sessions(limit: int = 100, status: str | None = None):
    """List Tempa Cursor background sessions for the dashboard monitor page."""
    from tempa.channels.slack import cursor_jobs as cursor_job_store
    from tempa.channels.slack.profiles import enrich_jobs

    jobs = cursor_job_store.list_jobs(limit=max(1, min(limit, 500)))
    if status:
        wanted = {s.strip() for s in status.split(",") if s.strip()}
        if wanted:
            jobs = [j for j in jobs if str(j.get("status") or "") in wanted]
    active = sum(
        1
        for j in cursor_job_store.list_jobs(limit=500)
        if str(j.get("status") or "") in cursor_job_store.ACTIVE_STATUSES
    )
    return {
        "sessions": enrich_jobs(jobs),
        "counts": {
            "listed": len(jobs),
            "active": active,
        },
    }


@router.get("/cursor/sessions/{job_id}")
async def api_cursor_session_detail(job_id: str):
    """One Cursor session: job fields, Slack conversation, and activity timeline."""
    from tempa.channels.slack import cursor_jobs as cursor_job_store
    from tempa.channels.slack.conversation import list_thread_messages
    from tempa.channels.slack.profiles import (
        enrich_jobs,
        enrich_turns,
        resolve_profiles,
        sync_participants_from_slack,
    )

    job = cursor_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")

    channel_id = str(job.get("channel_id") or "")
    thread_ts = str(job.get("thread_ts") or "")
    conversation = list_thread_messages(
        channel_id=channel_id,
        thread_ts=thread_ts,
        limit=300,
    )

    # Permanent source of truth: Slack thread membership → persisted on the job.
    slack_ids = sync_participants_from_slack(channel_id=channel_id, thread_ts=thread_ts)
    if slack_ids:
        refreshed = cursor_job_store.get_job(job_id) or job
        job = refreshed

    job = enrich_jobs([job])[0]
    conversation = enrich_turns(conversation)

    # Merge any humans present only in local turns (e.g. offline gaps).
    from tempa.channels.slack.conversation import participants_from_turns
    from tempa.channels.slack.cursor_jobs import add_thread_participants

    turn_ids = participants_from_turns(
        conversation,
        starter_user_id=str(job.get("user_id") or ""),
    )
    stored = [str(u) for u in (job.get("participant_ids") or []) if str(u).strip()]
    missing = [uid for uid in turn_ids if uid not in stored]
    if missing and channel_id and thread_ts:
        add_thread_participants(channel_id=channel_id, thread_ts=thread_ts, user_ids=missing)
        resolve_profiles(missing)
        job = enrich_jobs([cursor_job_store.get_job(job_id) or job])[0]

    activity: list[dict[str, Any]] = []
    if job.get("enqueued_at"):
        activity.append(
            {
                "at": job["enqueued_at"],
                "kind": "queued",
                "label": "Queued by Tempa",
                "detail": str(job.get("ask_text") or "")[:400],
            }
        )
    if job.get("started_at"):
        activity.append(
            {
                "at": job["started_at"],
                "kind": "running",
                "label": "Cursor started",
                "detail": f"mode={job.get('mode') or 'read'} repo={job.get('repo') or '—'}",
            }
        )
    if job.get("branch"):
        activity.append(
            {
                "at": job.get("updated_at") or job.get("started_at") or "",
                "kind": "branch",
                "label": f"Branch {job.get('branch')}",
                "detail": str(job.get("worktree_path") or "")[:300],
            }
        )
    if job.get("pr_url"):
        activity.append(
            {
                "at": job.get("updated_at") or "",
                "kind": "pr",
                "label": f"PR #{job.get('pr_number') or ''}".strip(),
                "detail": str(job.get("pr_url") or ""),
            }
        )
    if isinstance(job.get("ci_fix_count"), int) and job["ci_fix_count"] > 0:
        activity.append(
            {
                "at": job.get("updated_at") or "",
                "kind": "ci_fix",
                "label": f"CI fix attempts: {job['ci_fix_count']}",
                "detail": str(job.get("phase") or ""),
            }
        )
    if job.get("result_text"):
        activity.append(
            {
                "at": job.get("completed_at") or job.get("updated_at") or "",
                "kind": "result",
                "label": "Cursor result",
                "detail": str(job.get("result_text") or "")[:4000],
            }
        )
    if job.get("error"):
        activity.append(
            {
                "at": job.get("updated_at") or "",
                "kind": "error",
                "label": "Error",
                "detail": str(job.get("error") or "")[:2000],
            }
        )
    status = str(job.get("status") or "")
    if status in {"completed", "failed", "interrupted", "needs_help"} and job.get("completed_at"):
        activity.append(
            {
                "at": job["completed_at"],
                "kind": status,
                "label": f"Session {status}",
                "detail": "",
            }
        )

    return {
        "job": job,
        "conversation": conversation,
        "activity": activity,
    }


@router.get("/qa/repos")
async def api_qa_repos():
    from tempa.qa.installations import list_repos_detail

    return {"repos": list_repos_detail()}


@router.post("/qa/repos")
async def api_qa_add_repo(body: RepoRequest):
    from tempa.qa.allowed_repos import add_repo, normalize_repo

    name = normalize_repo(body.repo)
    if not name:
        raise HTTPException(status_code=400, detail="invalid_repo")
    try:
        record = add_repo(name, source="qa_dashboard")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_repo")
    return {"status": "added", "repo": record}


@router.delete("/qa/repos/{repo:path}")
async def api_qa_remove_repo(repo: str):
    from tempa.qa.allowed_repos import is_dynamic_repo, remove_repo

    name = repo.strip()
    if not is_dynamic_repo(name):
        raise HTTPException(status_code=400, detail="not_removable")
    if not remove_repo(name):
        raise HTTPException(status_code=404, detail="not_found")
    return {"status": "removed", "repo": name}


@router.post("/qa/scan")
async def api_qa_scan(body: ScanRequest):
    if not qa_enabled():
        raise HTTPException(status_code=503, detail="qa_disabled")
    from tempa.qa.github.parse import GitHubTarget
    from tempa.qa.scan_request import handle_github_scan_request

    target = GitHubTarget(repo=body.repo, branch=body.branch, pr_number=body.pr_number)
    result = handle_github_scan_request("", source_channel="qa_dashboard", target=target)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "scan_failed"))
    return result


@router.post("/qa/findings/{finding_id}/comment")
async def api_qa_comment(finding_id: str):
    try:
        return post_finding_comment(finding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/qa/findings/{finding_id}/fix")
async def api_qa_fix(finding_id: str):
    from tempa.core.pending_actions import create_pending_action
    from tempa.qa.fix.autofix import generate_fix_patch

    finding = get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="not_found")
    if not finding.get("file"):
        raise HTTPException(status_code=400, detail="finding_has_no_file")

    patch = await generate_fix_patch(finding)
    action = create_pending_action(
        "qa_autofix",
        {
            "finding_id": finding_id,
            "repo": finding.get("repo"),
            "branch": finding.get("branch"),
            "file": finding.get("file"),
            "title": finding.get("title"),
            "patch_content": patch.get("patch_content"),
        },
        source_channel="qa_dashboard",
        risk_level="high",
        title=f"QA fix: {finding.get('title', finding_id)[:80]}",
    )
    return {"status": "pending_approval", "action_id": action["id"]}


@router.get("/qa/findings/{finding_id}/agent-playbook")
async def api_qa_agent_playbook(finding_id: str, target: str = "claude"):
    from tempa.qa.agent_playbook import build_agent_playbook

    if target not in ("claude", "cursor"):
        raise HTTPException(status_code=400, detail="target must be claude or cursor")
    finding = get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="not_found")
    return build_agent_playbook(finding, target=target)  # type: ignore[arg-type]


@router.post("/qa/deep-review")
async def api_qa_deep_review(body: DeepReviewRequest):
    if not qa_enabled():
        raise HTTPException(status_code=503, detail="qa_disabled")
    repo = body.repo
    pr_number = body.pr_number
    if body.pr_url and not repo:
        import re

        m = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", body.pr_url)
        if m:
            repo, pr_number = m.group(1), int(m.group(2))
    if not repo:
        raise HTTPException(status_code=400, detail="repo_required")
    if not pr_number:
        raise HTTPException(status_code=400, detail="pr_number_required")

    from tempa.qa.github.parse import GitHubTarget
    from tempa.qa.scan_request import handle_github_scan_request

    result = handle_github_scan_request(
        body.pr_url or f"deep review PR #{pr_number} in {repo}",
        source_channel="qa_dashboard",
        requested_by="dashboard",
        target=GitHubTarget(repo=repo, pr_number=pr_number),
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "deep_review_failed"))
    return result
