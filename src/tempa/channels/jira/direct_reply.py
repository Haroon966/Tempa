from __future__ import annotations

from typing import Any

from tempa.agents.intent import extract_jira_issue_key, wants_jira


async def try_jira_direct_reply(user_message: str, context: dict[str, Any] | None = None) -> str | None:
    """Return a formatted Jira reply without LLM when the request is unambiguous."""
    if not wants_jira(user_message):
        return None

    from tempa.channels.jira.client import get_issue, jira_configured, list_projects, search_issues

    if not jira_configured():
        return "Jira isn't connected yet. Add your site URL, email, and API token in Tempa → Connections."

    lower = user_message.lower()
    if "project" in lower and any(w in lower for w in ("list", "show", "what", "my", "all")):
        projects = list_projects()
        if not projects:
            return "No Jira projects are visible to this account."
        lines = [f"• *{p['key']}* — {p['name']}" for p in projects[:30]]
        suffix = f"\n_(Showing {len(lines)} of {len(projects)}.)_" if len(projects) > 30 else ""
        return "Your Jira projects:\n" + "\n".join(lines) + suffix

    issue_key = extract_jira_issue_key(user_message)
    if issue_key:
        try:
            issue = get_issue(issue_key)
        except Exception as exc:
            return f"Could not load Jira issue {issue_key}: {exc}"
        lines = [
            f"*{issue['key']}*: {issue['summary']}",
            f"Status: {issue.get('status') or 'unknown'}",
            f"Assignee: {issue.get('assignee') or '(unassigned)'}",
        ]
        if issue.get("url"):
            lines.append(str(issue["url"]))
        return "\n".join(lines)

    if "search" in lower or "jql" in lower:
        jql = user_message if "jql" in lower else "ORDER BY updated DESC"
        try:
            issues = search_issues(jql, max_results=15)
        except Exception as exc:
            return f"Jira search failed: {exc}"
        if not issues:
            return "No Jira issues matched that search."
        lines = [f"• *{i['key']}*: {i['summary']} ({i.get('status') or ''})" for i in issues]
        return "Jira search results:\n" + "\n".join(lines)

    return None
