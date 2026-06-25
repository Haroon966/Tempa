"""Webhook event handlers."""

from __future__ import annotations

import logging
from typing import Any

from tempa.qa.config import load_qa_config, qa_enabled
from tempa.qa.installations import (
    add_repos_to_installation,
    remove_installation,
    remove_repos_from_installation,
    upsert_installation,
)
from tempa.qa.job_store import enqueue_scan

log = logging.getLogger(__name__)


def handle_installation(payload: dict[str, Any]) -> None:
    action = payload.get("action")
    installation = payload.get("installation") or {}
    inst_id = int(installation.get("id") or 0)
    account = str((installation.get("account") or {}).get("login") or "")
    if action == "deleted":
        remove_installation(inst_id)
        return
    repos = payload.get("repositories") or []
    repo_rows = [{"full_name": r.get("full_name"), "id": r.get("id")} for r in repos]
    upsert_installation(inst_id, account, repo_rows)


def handle_installation_repositories(payload: dict[str, Any]) -> None:
    installation = payload.get("installation") or {}
    inst_id = int(installation.get("id") or 0)
    added = payload.get("repositories_added") or []
    removed = payload.get("repositories_removed") or []
    if added:
        add_repos_to_installation(inst_id, [{"full_name": r.get("full_name"), "id": r.get("id")} for r in added])
    if removed:
        remove_repos_from_installation(inst_id, [str(r.get("full_name") or "") for r in removed])


def handle_push(payload: dict[str, Any]) -> None:
    if not qa_enabled() or not load_qa_config().get("scan_on_push", True):
        return
    repo = str((payload.get("repository") or {}).get("full_name") or "")
    ref = str(payload.get("ref") or "")
    if not repo or not ref.startswith("refs/heads/"):
        return
    branch = ref.removeprefix("refs/heads/")
    inst_id = int((payload.get("installation") or {}).get("id") or 0)
    enqueue_scan(repo, branch=branch, installation_id=inst_id or None, job_type="branch_scan")


def handle_pull_request(payload: dict[str, Any]) -> None:
    if not qa_enabled() or not load_qa_config().get("scan_on_pr", True):
        return
    action = payload.get("action")
    if action not in ("opened", "synchronize", "reopened", "labeled"):
        return
    pr = payload.get("pull_request") or {}
    repo = str((payload.get("repository") or {}).get("full_name") or "")
    branch = str((pr.get("head") or {}).get("ref") or "")
    pr_number = int(pr.get("number") or 0)
    inst_id = int((payload.get("installation") or {}).get("id") or 0)
    label_name = load_qa_config().get("deep_review_on_label") or "tempa-deep-review"
    if action == "labeled":
        label = str((payload.get("label") or {}).get("name") or "")
        if label == label_name:
            enqueue_scan(
                repo,
                branch=branch,
                pr_number=pr_number,
                installation_id=inst_id or None,
                job_type="deep_review",
            )
        return
    enqueue_scan(
        repo,
        branch=branch,
        pr_number=pr_number,
        installation_id=inst_id or None,
        job_type="branch_scan",
    )


def handle_check_run(payload: dict[str, Any]) -> None:
    from tempa.qa.handlers.ci import handle_ci_failure

    handle_ci_failure(payload)


def handle_issue_comment(payload: dict[str, Any]) -> None:
    from tempa.qa.handlers.comments import handle_comment

    handle_comment(payload)


def dispatch_event(event: str, payload: dict[str, Any]) -> None:
    if not qa_enabled():
        return
    handlers = {
        "installation": handle_installation,
        "installation_repositories": handle_installation_repositories,
        "push": handle_push,
        "pull_request": handle_pull_request,
        "check_run": handle_check_run,
        "issue_comment": handle_issue_comment,
    }
    handler = handlers.get(event)
    if handler:
        try:
            handler(payload)
        except Exception:
            log.exception("QA handler failed for event %s", event)
