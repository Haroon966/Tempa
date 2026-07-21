"""Format QA scan/review results for chat replies."""

from __future__ import annotations

from typing import Any

from tempa.qa.github.parse import parse_github_target
from tempa.qa.job_store import list_jobs
from tempa.qa.store import list_branch_statuses, list_findings


def resolve_qa_repo_from_context(user_message: str, context: dict[str, Any] | None = None) -> str:
    """Prefer an explicit repo in the message; otherwise the latest QA-related conversation turn."""
    target = parse_github_target(user_message or "")
    if target.repo:
        return target.repo

    ctx = context or {}
    candidates: list[str] = []
    for key in ("recent_user_messages",):
        for item in ctx.get(key) or []:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                candidates.append(str(item.get("text") or item.get("content") or ""))
    for turn in ctx.get("recent_conversation") or ctx.get("conversation_messages") or []:
        if isinstance(turn, dict):
            candidates.append(str(turn.get("text") or turn.get("content") or ""))
        elif isinstance(turn, str):
            candidates.append(turn)
    # Most recent first
    for text in reversed(candidates):
        parsed = parse_github_target(text)
        if parsed.repo:
            return parsed.repo

    # Last completed QA job as last resort
    for job in list_jobs(limit=20):
        repo = str(job.get("repo") or "")
        if repo and "/" in repo and "github.com" not in repo:
            return repo
    return ""


def format_qa_results_reply(repo: str) -> str:
    """Build a concise findings summary for a repo (or say the scan is still running / clean)."""
    name = (repo or "").strip()
    if not name:
        return (
            "I don't see which repo you mean. Send a GitHub link "
            "(or ask again after a QA request) and I'll report the findings."
        )

    jobs = [j for j in list_jobs(limit=50) if str(j.get("repo") or "") == name]
    running = [j for j in jobs if j.get("status") in ("queued", "running")]
    branches = list_branch_statuses(repo=name)
    findings = list_findings(repo=name, status="open", limit=20)

    if running and not branches and not findings:
        kinds = sorted({str(j.get("job_type") or "scan") for j in running})
        return (
            f"QA for `{name}` is still {running[0].get('status')} "
            f"({', '.join(kinds)}). I'll have results shortly — ask again in a minute."
        )

    lines = [f"## QA results for `{name}`"]
    if branches:
        lines.append("")
        lines.append("**Branch health**")
        for b in branches[:8]:
            lines.append(
                f"- `{b.get('branch')}` — grade **{b.get('grade', '—')}** "
                f"(CI: {b.get('ci_status', '?')}, lint: {b.get('lint_status', '?')}, "
                f"tests: {b.get('test_status', '?')}, security: {b.get('security_count', 0)})"
            )
    elif jobs:
        latest = jobs[0]
        lines.append(
            f"\nLatest job: `{latest.get('job_type')}` — **{latest.get('status')}**"
            + (f" ({latest.get('error')})" if latest.get("error") else "")
        )

    if not findings:
        lines.append("")
        lines.append("No open findings — no errors or bugs recorded from the last QA run.")
        if branches and all(
            str(b.get("lint_status")) == "skipped" and str(b.get("test_status")) == "skipped"
            for b in branches
        ):
            lines.append(
                "_Note: lint/tests were skipped for this checkout "
                "(often means no matching local check paths in the repo)._"
            )
        return "\n".join(lines)

    lines.append("")
    lines.append(f"**Open findings ({len(findings)})**")
    for f in findings[:12]:
        sev = str(f.get("severity") or "medium").upper()
        title = str(f.get("title") or "Finding")
        loc = ""
        if f.get("file"):
            loc = f" — `{f.get('file')}`" + (f":{f.get('line')}" if f.get("line") else "")
        lines.append(f"- **{sev}**: {title}{loc}")
    if len(findings) > 12:
        lines.append(f"- …and {len(findings) - 12} more (see the QA dashboard).")
    return "\n".join(lines)
