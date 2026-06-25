"""Slash command handler for GitHub comments."""

from __future__ import annotations

import logging
import re
from typing import Any

from tempa.qa.github.auth import get_installation_token
from tempa.qa.github.client import gh_post
from tempa.qa.job_store import enqueue_scan

log = logging.getLogger(__name__)

COMMANDS = {
    "/fix",
    "/security",
    "/ci",
    "/health",
    "/deep-review",
    "/scan",
}


def handle_comment(payload: dict[str, Any]) -> None:
    if payload.get("action") != "created":
        return
    comment = payload.get("comment") or {}
    body = str(comment.get("body") or "").strip()
    if not body.startswith("/"):
        return
    cmd = body.split()[0].lower()
    if cmd not in COMMANDS:
        return

    repo = str((payload.get("repository") or {}).get("full_name") or "")
    installation_id = int((payload.get("installation") or {}).get("id") or 0)
    issue = payload.get("issue") or {}
    issue_number = int(issue.get("number") or 0)
    if not repo or not installation_id:
        return

    try:
        token = get_installation_token(installation_id)
    except Exception as exc:
        log.error("comment handler auth failed: %s", exc)
        return

    if cmd == "/scan":
        enqueue_scan(repo, installation_id=installation_id, job_type="repo_scan")
        gh_post(
            f"/repos/{repo}/issues/{issue_number}/comments",
            token,
            {"body": "Queued full repository branch scan."},
        )
        return

    if cmd == "/deep-review":
        pr_match = re.search(r"/pull/(\d+)", str(issue.get("pull_request", {}).get("url") or ""))
        pr_number = int(pr_match.group(1)) if pr_match else issue_number
        enqueue_scan(repo, pr_number=pr_number, installation_id=installation_id, job_type="deep_review")
        gh_post(
            f"/repos/{repo}/issues/{issue_number}/comments",
            token,
            {"body": f"Queued deep review for PR #{pr_number}."},
        )
        return

    if cmd == "/security":
        from tempa.qa.security.scanner import run_security_scan

        report = run_security_scan(repo, token)
        gh_post(
            f"/repos/{repo}/issues/{issue_number}/comments",
            token,
            {"body": report.to_markdown()},
        )
        return

    if cmd == "/health":
        from tempa.qa.store import list_branch_statuses, summary_stats

        stats = summary_stats()
        branches = list_branch_statuses(repo=repo)
        failing = [b for b in branches if b.get("grade") in ("D", "F")]
        gh_post(
            f"/repos/{repo}/issues/{issue_number}/comments",
            token,
            {
                "body": (
                    f"## Repo Health\n\n"
                    f"- Branches scanned: {len(branches)}\n"
                    f"- Failing grades: {len(failing)}\n"
                    f"- Open findings: {stats.get('open_findings', 0)}\n"
                    f"- Queue depth: {stats.get('queue_depth', 0)}\n"
                )
            },
        )
        return

    gh_post(
        f"/repos/{repo}/issues/{issue_number}/comments",
        token,
        {"body": f"Command `{cmd}` acknowledged. Use the Tempa QA dashboard for full actions."},
    )
