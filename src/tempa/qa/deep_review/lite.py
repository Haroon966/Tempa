"""Deep PR review — Claude by default, Groq fallback."""

from __future__ import annotations

import json
import logging
from typing import Any

from tempa.qa.github.parse import parse_pr_from_text  # noqa: F401 — re-export
from tempa.qa.github.auth import get_github_token, github_uses_pat
from tempa.qa.github.client import gh_get
from tempa.qa.installations import installation_id_for_repo
from tempa.qa.llm import deep_review_complete
from tempa.qa.store import add_finding

log = logging.getLogger(__name__)


async def run_deep_review(
    repo: str,
    pr_number: int,
    *,
    installation_id: int | None = None,
    scan_job_id: str = "",
) -> dict[str, Any]:
    inst_id = installation_id or installation_id_for_repo(repo)
    if not inst_id and not github_uses_pat():
        raise RuntimeError(f"No installation for {repo}")
    token = get_github_token(repo)

    pr = gh_get(f"/repos/{repo}/pulls/{pr_number}", token)
    branch = str((pr.get("head") or {}).get("ref") or "")
    files = gh_get(f"/repos/{repo}/pulls/{pr_number}/files", token)
    if not isinstance(files, list):
        files = []

    diff_parts: list[str] = []
    for f in files[:30]:
        diff_parts.append(f"### {f.get('filename')}\n{f.get('patch', '')[:2000]}")
    diff_text = "\n\n".join(diff_parts)[:12000]

    from tempa.qa.claude import claude_configured

    provider = "claude" if claude_configured() else "groq"
    prompt = f"Deep review PR #{pr_number} in {repo}:\n{diff_text}"
    text = await deep_review_complete(prompt, max_tokens=4096)

    findings_raw = _parse_findings(text)
    created = 0
    for item in findings_raw:
        sev = str(item.get("severity") or "suggestion")
        severity = "critical" if sev == "critical" else "high" if sev == "important" else "medium"
        add_finding(
            repo=repo,
            branch=branch,
            category="security" if "security" in str(item.get("title", "")).lower() else "other",
            severity=severity,
            title=str(item.get("title") or "Review finding"),
            body=str(item.get("body") or ""),
            suggestion=str(item.get("suggestion") or ""),
            file=str(item.get("file") or ""),
            line=int(item.get("line") or 0),
            pr_number=pr_number,
            scan_job_id=scan_job_id,
        )
        created += 1

    return {
        "pr_number": pr_number,
        "findings_created": created,
        "branch": branch,
        "provider": provider,
    }



def _parse_findings(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip().strip("`").removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "findings" in data:
            return list(data["findings"])
    except json.JSONDecodeError:
        pass
    return [{"severity": "suggestion", "title": "Deep review completed", "body": text[:2000]}]
