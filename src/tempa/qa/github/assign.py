"""Ensure a PR has an assignee before QA review."""

from __future__ import annotations

import logging
from typing import Any

from tempa.qa.github.auth import get_github_token
from tempa.qa.github.client import gh_get, gh_post

log = logging.getLogger(__name__)

_SKIP_USERS = frozenset({"github-actions", "dependabot", "renovate", "codecov", "sonarcloud"})
_TEMPA_MARKERS = ("Tempa QA", "Posted by Tempa QA Agent")


def _is_bot(login: str) -> bool:
    name = (login or "").strip()
    if not name:
        return True
    lower = name.lower()
    return lower in _SKIP_USERS or lower.endswith("[bot]") or name.endswith("[bot]")


def _first_human_commenter(repo: str, pr_number: int, token: str) -> str | None:
    comments = gh_get(
        f"/repos/{repo}/issues/{pr_number}/comments?per_page=30&sort=created&direction=asc",
        token,
    )
    if not isinstance(comments, list):
        return None
    for comment in comments:
        login = str((comment.get("user") or {}).get("login") or "")
        if _is_bot(login):
            continue
        body = str(comment.get("body") or "")
        if any(marker in body for marker in _TEMPA_MARKERS):
            continue
        return login
    return None


def ensure_pr_assignee(repo: str, pr_number: int) -> dict[str, Any]:
    """If the PR has no assignees, assign the first human commenter (else the PR author).

    Never blocks QA: assignment failures are returned as status=error but do not raise.
    """
    if not repo or not pr_number:
        return {"status": "skipped", "reason": "missing_repo_or_pr"}

    token = get_github_token(repo)
    try:
        pr = gh_get(f"/repos/{repo}/pulls/{pr_number}", token)
    except Exception as exc:
        log.warning("qa.assign: cannot load PR %s#%s: %s", repo, pr_number, exc)
        return {"status": "error", "reason": str(exc)}

    existing = [
        str((a or {}).get("login") or "")
        for a in (pr.get("assignees") or [])
        if (a or {}).get("login")
    ]
    if existing:
        return {"status": "already_assigned", "assignees": existing}

    author = str((pr.get("user") or {}).get("login") or "")
    commenter = None
    try:
        commenter = _first_human_commenter(repo, pr_number, token)
    except Exception as exc:
        log.warning("qa.assign: comment lookup failed for %s#%s: %s", repo, pr_number, exc)

    target = commenter or author
    reason = "first_comment" if commenter else "pr_author"
    if not target:
        return {"status": "skipped", "reason": "no_candidate"}

    try:
        resp = gh_post(
            f"/repos/{repo}/issues/{pr_number}/assignees",
            token,
            {"assignees": [target]},
        )
    except Exception as exc:
        log.warning("qa.assign: failed to assign %s on %s#%s: %s", target, repo, pr_number, exc)
        return {"status": "error", "assignee": target, "reason": str(exc)}

    assignees = [
        str((a or {}).get("login") or "")
        for a in (resp.get("assignees") or [])
        if (a or {}).get("login")
    ]
    log.info("qa.assign: assigned %s on %s#%s (%s)", target, repo, pr_number, reason)
    return {
        "status": "assigned",
        "assignee": target,
        "reason": reason,
        "assignees": assignees or [target],
    }
