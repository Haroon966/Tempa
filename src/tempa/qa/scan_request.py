"""Central GitHub QA scan routing for dashboard, chat, and API."""

from __future__ import annotations

from typing import Any

from tempa.qa.allowed_repos import add_repo, normalize_repo
from tempa.qa.github.auth import github_configured, github_uses_pat
from tempa.qa.github.parse import GitHubTarget, parse_github_target, wants_scan_all
from tempa.qa.installations import installation_id_for_repo, list_repos
from tempa.qa.job_store import enqueue_scan


def repo_is_allowed(repo: str) -> bool:
    name = normalize_repo(repo)
    if not name:
        return False
    return name in list_repos()


def enqueue_target_scan(target: GitHubTarget) -> str:
    repo = normalize_repo(target.repo)
    if not repo:
        raise ValueError("invalid_repo")
    inst_id = installation_id_for_repo(repo)
    if target.pr_number:
        return enqueue_scan(
            repo,
            pr_number=target.pr_number,
            installation_id=inst_id,
            job_type="deep_review",
        )
    if target.branch:
        return enqueue_scan(
            repo,
            branch=target.branch,
            installation_id=inst_id,
            job_type="branch_scan",
        )
    return enqueue_scan(repo, installation_id=inst_id, job_type="repo_scan")


def _scan_title(target: GitHubTarget, *, add_to_allowlist: bool) -> str:
    parts = [f"QA scan: {target.repo}"]
    if target.branch:
        parts.append(f"branch {target.branch}")
    if target.pr_number:
        parts.append(f"PR #{target.pr_number}")
    if add_to_allowlist:
        parts.append("(add repo to allowlist)")
    return " ".join(parts)


def handle_github_scan_request(
    text: str,
    *,
    source_channel: str = "coordinator",
    target: GitHubTarget | None = None,
) -> dict[str, Any]:
    from tempa.qa.config import qa_enabled

    if not qa_enabled():
        return {"status": "disabled", "message": "QA agent is disabled."}
    if not github_configured():
        return {"status": "error", "message": "GitHub is not configured. Set GITHUB_TOKEN or GitHub App credentials."}

    parsed = target or parse_github_target(text)

    if wants_scan_all(text) and not parsed.repo:
        repos = list_repos()
        if not repos:
            return {
                "status": "error",
                "message": "No GitHub repos configured. Add repos in the QA dashboard or set GITHUB_REPOS.",
            }
        jobs = [enqueue_target_scan(GitHubTarget(repo=r)) for r in repos]
        return {"status": "queued", "jobs": jobs, "repos": repos}

    if not parsed.repo:
        repos = list_repos()
        if repos and source_channel in ("coordinator", "whatsapp", "slack"):
            return {
                "status": "error",
                "message": (
                    "Specify a repo (e.g. owner/repo or a GitHub URL). "
                    f"Configured repos: {', '.join(repos[:5])}"
                    + ("…" if len(repos) > 5 else "")
                ),
            }
        return {
            "status": "error",
            "message": "Could not detect a GitHub repo. Send a link or owner/repo name.",
        }

    add_to_allowlist = github_uses_pat() and not repo_is_allowed(parsed.repo)
    trusted_source = source_channel in ("qa_dashboard", "api")

    if add_to_allowlist and not trusted_source:
        from tempa.core.pending_actions import create_pending_action

        action = create_pending_action(
            "qa_repo_scan",
            {
                "repo": parsed.repo,
                "branch": parsed.branch,
                "pr_number": parsed.pr_number,
                "add_to_allowlist": True,
                "source_channel": source_channel,
            },
            source_channel=source_channel,
            risk_level="medium",
            title=_scan_title(parsed, add_to_allowlist=True),
        )
        return {
            "status": "pending_approval",
            "action_id": action["id"],
            "repo": parsed.repo,
            "branch": parsed.branch,
            "pr_number": parsed.pr_number,
            "message": (
                f"Repo `{parsed.repo}` is not on the allowlist. "
                "Approve in the dashboard Pending tab to add it and run the scan."
            ),
        }

    if add_to_allowlist and trusted_source:
        add_repo(parsed.repo, source=source_channel)

    job_id = enqueue_target_scan(parsed)
    return {
        "status": "queued",
        "job_id": job_id,
        "repo": parsed.repo,
        "branch": parsed.branch,
        "pr_number": parsed.pr_number,
    }
