"""QA API routes."""

from __future__ import annotations

import json
import logging

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
    limit: int = 100,
):
    return {"findings": list_findings(repo=repo, branch=branch, status=status, limit=limit)}


@router.get("/qa/jobs")
async def api_qa_jobs(limit: int = 50):
    return {"jobs": list_jobs(limit=limit)}


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
    """Legacy alias — returns agent playbook instructions instead of running Claude API."""
    repo = body.repo
    pr_number = body.pr_number
    if body.pr_url and not repo:
        import re

        m = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", body.pr_url)
        if m:
            repo, pr_number = m.group(1), int(m.group(2))
    if not repo:
        raise HTTPException(status_code=400, detail="repo_required")
    return {
        "status": "use_terminal_agent",
        "message": "Deep review runs in Claude Code or Cursor. Use GET /api/qa/findings/{id}/agent-playbook",
        "repo": repo,
        "pr_number": pr_number,
    }
