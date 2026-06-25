"""Post GitHub comments for QA findings."""

from __future__ import annotations

import logging

from tempa.qa.github.auth import get_installation_token
from tempa.qa.github.client import gh_post
from tempa.qa.installations import installation_id_for_repo
from tempa.qa.store import get_finding, update_finding

log = logging.getLogger(__name__)


def post_finding_comment(finding_id: str) -> dict:
    finding = get_finding(finding_id)
    if not finding:
        raise ValueError("finding not found")

    repo = str(finding.get("repo") or "")
    inst_id = installation_id_for_repo(repo)
    if not inst_id:
        raise RuntimeError(f"No installation for repo {repo}")

    token = get_installation_token(inst_id)
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
