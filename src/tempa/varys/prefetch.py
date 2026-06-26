from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_GITHUB_REPO_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)", re.I)
_ENGLISH_REPLY_RE = re.compile(r"\breply(?:\s+me)?\s+in\s+english\b", re.I)


def wants_english_reply(text: str) -> bool:
    return bool(_ENGLISH_REPLY_RE.search(text or ""))


def _github_repo_from_text(text: str) -> str:
    match = _GITHUB_REPO_RE.search(text or "")
    if not match:
        return ""
    return match.group(1).rstrip("/.")


async def _fetch_github_repo_summary(repo: str) -> str:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "tempa-varys"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            meta_resp = await client.get(f"https://api.github.com/repos/{repo}", headers=headers)
            if meta_resp.status_code != 200:
                return f"GitHub repo `{repo}`: API returned {meta_resp.status_code}."
            meta = meta_resp.json()
            lines = [
                f"Repository: {meta.get('full_name', repo)}",
                f"Description: {meta.get('description') or '(none)'}",
                f"Language: {meta.get('language') or 'unknown'}",
                f"Default branch: {meta.get('default_branch', 'main')}",
                f"Open issues: {meta.get('open_issues_count', 0)}",
                f"Stars: {meta.get('stargazers_count', 0)}",
                f"Private: {meta.get('private', False)}",
            ]
            readme_resp = await client.get(
                f"https://api.github.com/repos/{repo}/readme",
                headers={**headers, "Accept": "application/vnd.github.raw"},
            )
            if readme_resp.status_code == 200:
                readme = readme_resp.text.strip()
                if readme:
                    lines.append("README excerpt:\n" + readme[:2500])
            issues_resp = await client.get(
                f"https://api.github.com/repos/{repo}/issues",
                headers=headers,
                params={"state": "open", "per_page": 5},
            )
            if issues_resp.status_code == 200:
                issues = issues_resp.json()
                if issues:
                    lines.append("Open issues:")
                    for issue in issues[:5]:
                        if issue.get("pull_request"):
                            continue
                        lines.append(f"- #{issue.get('number')}: {issue.get('title')}")
    except Exception as exc:
        logger.warning("GitHub prefetch failed for %s: %s", repo, exc)
        return f"Could not fetch GitHub repo `{repo}`: {exc}"
    else:
        return "\n".join(lines)


async def _prefetch_slack(user_message: str, context: dict[str, Any]) -> str:
    from tempa.agents.specialists import _slack_read_query_from_context, run_channel_agent

    ctx = {**context, "user_message": user_message}
    try:
        payload = await run_channel_agent(user_message, ctx)
    except Exception as exc:
        logger.warning("Slack prefetch failed: %s", exc)
        return ""

    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return f"## Slack tool result\n{payload}"

    if data.get("help"):
        return "## Slack help\n" + str(data.get("message") or "")
    if data.get("status") == "ok" and data.get("message"):
        parts = ["## Slack channel lookup"]
        parts.append(f"Channel: #{data.get('channel', '')}")
        if data.get("user"):
            parts.append(f"From: {data['user']}")
        if data.get("timestamp"):
            parts.append(f"When: {data['timestamp']}")
        parts.append(str(data["message"])[:4000])
        return "\n".join(parts)
    if data.get("status") == "error" and data.get("reason"):
        read_query = _slack_read_query_from_context(user_message, context)
        from tempa.channels.slack.lookup import wants_slack_read_intent

        if wants_slack_read_intent(read_query):
            return "## Slack channel lookup\n" + str(data["reason"])
    return ""


async def prefetch_tool_context(user_message: str, context: dict[str, Any] | None = None) -> str:
    """Run channel/QA lookups before the Varys LLM so replies use real data."""
    ctx = dict(context or {})
    parts: list[str] = []

    if ctx.get("channel") == "slack" or ctx.get("inbound_slack"):
        slack_block = await _prefetch_slack(user_message, ctx)
        if slack_block:
            parts.append(slack_block)

    from tempa.qa.github.parse import parse_github_target, wants_github_qa

    if wants_github_qa(user_message) or parse_github_target(user_message).repo:
        target = parse_github_target(user_message)
        if target.repo:
            parts.append("## GitHub repo data\n" + await _fetch_github_repo_summary(target.repo))
        from tempa.qa.config import qa_enabled

        if qa_enabled() and (target.repo or any(k in user_message.lower() for k in ("scan", "audit", "run qa"))):
            try:
                from tempa.qa.scan_request import handle_github_scan_request

                channel = str(ctx.get("channel") or ("slack" if ctx.get("inbound_slack") else "coordinator"))
                result = handle_github_scan_request(user_message, source_channel=channel)
                status = result.get("status")
                if status == "queued":
                    parts.append(
                        f"## QA scan queued\nJob `{result.get('job_id')}` for `{result.get('repo')}`"
                        + (f" branch `{result.get('branch')}`" if result.get("branch") else "")
                        + (f" PR #{result.get('pr_number')}" if result.get("pr_number") else "")
                        + " — check QA dashboard for findings."
                    )
                elif status == "pending_approval":
                    parts.append(f"## QA scan pending approval\n{result.get('message', '')}")
                elif status == "error":
                    parts.append(f"## QA scan\n{result.get('message', '')}")
            except Exception as exc:
                logger.debug("QA enqueue skipped: %s", exc)

    if wants_english_reply(user_message):
        parts.append("## Language\nUser asked for replies in English.")

    from tempa.agents.intent import wants_jira, extract_jira_issue_key

    if wants_jira(user_message):
        from tempa.channels.jira.client import jira_configured, get_issue, search_issues

        if jira_configured():
            issue_key = extract_jira_issue_key(user_message)
            if issue_key:
                try:
                    issue = get_issue(issue_key)
                    parts.append(
                        "## Jira issue\n"
                        + f"- **{issue.get('key')}**: {issue.get('summary')}\n"
                        + f"- Status: {issue.get('status')}\n"
                        + f"- Assignee: {issue.get('assignee') or '(unassigned)'}\n"
                        + f"- URL: {issue.get('url')}"
                    )
                except Exception as exc:
                    parts.append(f"## Jira\nCould not load issue: {exc}")
            elif "jql" in user_message.lower() or "search" in user_message.lower():
                try:
                    jql = user_message if "jql" in user_message.lower() else 'status != Done ORDER BY updated DESC'
                    issues = search_issues(jql, max_results=10)
                    lines = ["## Jira search results"]
                    for issue in issues[:10]:
                        lines.append(f"- {issue.get('key')}: {issue.get('summary')} ({issue.get('status')})")
                    parts.append("\n".join(lines))
                except Exception as exc:
                    parts.append(f"## Jira\nSearch failed: {exc}")

    return "\n\n".join(parts)
