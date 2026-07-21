"""Post GitHub comments for QA findings."""

from __future__ import annotations

import logging

from tempa.qa.github.auth import get_github_token
from tempa.qa.github.client import gh_post
from tempa.qa.store import get_finding, update_finding

log = logging.getLogger(__name__)


def post_finding_comment(finding_id: str) -> dict:
    finding = get_finding(finding_id)
    if not finding:
        raise ValueError("finding not found")

    repo = str(finding.get("repo") or "")
    token = get_github_token(repo)
    pr_number = finding.get("pr_number")
    body = _format_comment(finding)

    if pr_number:
        resp = gh_post(f"/repos/{repo}/issues/{int(pr_number)}/comments", token, {"body": body})
    else:
        title = f"[QA] {finding.get('title', 'Finding')} on `{finding.get('branch', '')}`"
        resp = gh_post(
            f"/repos/{repo}/issues",
            token,
            {"title": title, "body": body, "labels": ["tempa-qa"]},
        )

    url = str(resp.get("html_url") or "")
    update_finding(finding_id, github_comment_url=url)
    return {"status": "posted", "url": url}


def post_review_summary(
    repo: str,
    pr_number: int,
    findings: list[dict],
    *,
    branch_status: dict | None = None,
) -> dict:
    """Post one summary comment for a deep review (per-finding comments would spam the PR)."""
    token = get_github_token(repo)
    order = ("critical", "high", "medium", "low", "info")
    parts = [f"## Tempa QA — Deep review ({len(findings)} finding{'s' if len(findings) != 1 else ''})"]
    if branch_status:
        parts.extend(
            [
                "",
                f"**Branch `{branch_status.get('branch', '')}` checks** — grade **{branch_status.get('grade', '—')}**",
                f"- CI: {branch_status.get('ci_status', 'unknown')}"
                f" · Lint: {branch_status.get('lint_status', 'unknown')}"
                f" · Tests: {branch_status.get('test_status', 'unknown')}"
                f" · Security findings: {branch_status.get('security_count', 0)}",
            ]
        )
    for sev in order:
        group = [f for f in findings if str(f.get("severity") or "medium") == sev]
        if not group:
            continue
        parts.extend(["", f"### {sev.upper()}"])
        for f in group:
            loc = f" — `{f['file']}`" + (f":{f['line']}" if f.get("line") else "") if f.get("file") else ""
            parts.append(f"- **{f.get('title', 'Finding')}**{loc}")
            if f.get("body"):
                parts.append(f"  {str(f['body'])[:400]}")
            if f.get("suggestion"):
                parts.append(f"  _Suggested fix:_ {str(f['suggestion'])[:300]}")
    if not findings:
        parts.append("\nNo issues found in this diff.")
    parts.extend(["", "---", "*Posted by Tempa QA Agent*"])

    resp = gh_post(f"/repos/{repo}/issues/{int(pr_number)}/comments", token, {"body": "\n".join(parts)})
    url = str(resp.get("html_url") or "")
    for f in findings:
        if f.get("id"):
            update_finding(str(f["id"]), github_comment_url=url)
    return {"status": "posted", "url": url}


def _format_comment(finding: dict) -> str:
    parts = [
        f"## QA Finding — {finding.get('severity', 'medium').upper()}",
        f"**Category:** {finding.get('category')}",
        f"**Branch:** `{finding.get('branch', '')}`",
        "",
        str(finding.get("body") or finding.get("title") or ""),
    ]
    if finding.get("suggestion"):
        parts.extend(["", "### Suggested fix", str(finding["suggestion"])])
    parts.extend(["", "---", "*Posted by Tempa QA Agent*"])
    return "\n".join(parts)
