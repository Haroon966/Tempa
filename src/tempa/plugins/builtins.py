from __future__ import annotations

import json
from typing import Any

from tempa.plugins.registry import register_tool


def _register_memory_tools() -> None:
    from tempa.rag.ingest import search_memory
    from tempa.rag.filters import extract_filters_from_query

    def memory_search(query: str = "", top_k: int = 5) -> dict[str, Any]:
        filters = extract_filters_from_query(query)
        results = search_memory(
            query,
            top_k=top_k,
            tool=filters.get("tool"),
            date_from=filters.get("date_from"),
            date_to=filters.get("date_to"),
            participant=filters.get("participant"),
            tags=filters.get("tags"),
        )
        return {"count": len(results), "results": results}

    register_tool(
        "memory.search",
        "Search unified Agentic RAG memory across all channels",
        memory_search,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    )


def _register_gmail_tools() -> None:
    from tempa.channels.gmail.oauth import load_gmail_client
    from tempa.channels.gmail.query import extract_gmail_query
    from tempa.channels.gmail.ingest import message_to_text

    def gmail_search(query: str = "", max_results: int = 5) -> dict[str, Any]:
        client = load_gmail_client()
        if client is None:
            return {"status": "error", "reason": "Gmail not connected"}
        q = extract_gmail_query(query) or query
        messages = client.list_messages(query=q, max_results=max_results)
        payload = [
            {
                "id": m.id,
                "subject": m.subject,
                "from": m.sender,
                "snippet": m.snippet,
                "preview": message_to_text(m)[:400],
            }
            for m in messages
        ]
        return {"status": "ok", "query": q, "count": len(payload), "messages": payload}

    register_tool(
        "gmail.search",
        "Search Gmail inbox with a query string",
        gmail_search,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    )


def _register_calendar_tools() -> None:
    from datetime import datetime, timedelta, timezone

    from tempa.channels.calendar.oauth import load_calendar_client

    def calendar_list_events(days: int = 7) -> dict[str, Any]:
        client = load_calendar_client()
        if client is None:
            return {"status": "error", "reason": "Google Calendar not connected"}
        now = datetime.now(timezone.utc)
        events = client.list_upcoming_events(
            calendar_id="primary",
            time_min=now,
            time_max=now + timedelta(days=days),
        )
        payload = [
            {
                "summary": e.summary,
                "start": e.start.isoformat(),
                "meet_url": e.meet_url,
            }
            for e in events[:20]
        ]
        return {"status": "ok", "count": len(payload), "events": payload}

    register_tool(
        "calendar.list_events",
        "List upcoming Google Calendar events",
        calendar_list_events,
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
        },
    )


def _register_meet_tools() -> None:
    def meet_join(meet_url: str = "", title: str = "") -> dict[str, Any]:
        from tempa.meet.service import schedule_meeting_join

        if "meet.google.com" not in meet_url:
            return {"status": "error", "reason": "Invalid Google Meet URL"}
        try:
            meeting_id = schedule_meeting_join(meet_url, title=title or meet_url)
        except RuntimeError as exc:
            return {"status": "error", "reason": str(exc)}
        return {"status": "queued", "meeting_id": meeting_id, "meet_url": meet_url}

    register_tool(
        "meet.join",
        "Queue a Google Meet join for the given meet.google.com URL",
        meet_join,
        input_schema={
            "type": "object",
            "properties": {
                "meet_url": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["meet_url"],
        },
    )


def _register_preference_tools() -> None:
    from tempa.rag.procedural import add_preference, list_preferences

    register_tool(
        "memory.add_preference",
        "Store a user preference or procedural rule",
        lambda rule="": add_preference(rule, source="plugin"),
        input_schema={
            "type": "object",
            "properties": {"rule": {"type": "string"}},
            "required": ["rule"],
        },
    )
    register_tool(
        "memory.list_preferences",
        "List stored user preferences",
        lambda: {"preferences": list_preferences()},
        input_schema={"type": "object", "properties": {}},
    )


def _register_jira_tools() -> None:
    from tempa.channels.jira.client import get_issue, jira_configured, list_projects, search_issues

    def jira_search(jql: str = "", max_results: int = 25) -> dict[str, Any]:
        if not jira_configured():
            return {"status": "error", "reason": "Jira not connected"}
        if not jql.strip():
            from tempa.channels.jira.session import load_jira_session_config

            project = load_jira_session_config().get("default_project", "")
            jql = f"project = {project} ORDER BY updated DESC" if project else "ORDER BY updated DESC"
        issues = search_issues(jql, max_results=max_results)
        return {"status": "ok", "count": len(issues), "issues": issues}

    def jira_get_issue(issue_key: str = "") -> dict[str, Any]:
        if not jira_configured():
            return {"status": "error", "reason": "Jira not connected"}
        if not issue_key.strip():
            return {"status": "error", "reason": "issue_key required"}
        issue = get_issue(issue_key.strip().upper())
        return {"status": "ok", "issue": issue}

    def jira_list_projects() -> dict[str, Any]:
        if not jira_configured():
            return {"status": "error", "reason": "Jira not connected"}
        projects = list_projects()
        return {"status": "ok", "count": len(projects), "projects": projects}

    register_tool(
        "jira.search",
        "Search Jira issues with JQL",
        jira_search,
        input_schema={
            "type": "object",
            "properties": {
                "jql": {"type": "string"},
                "max_results": {"type": "integer", "default": 25},
            },
        },
    )
    register_tool(
        "jira.get_issue",
        "Get a Jira issue by key (e.g. ENG-123)",
        jira_get_issue,
        input_schema={
            "type": "object",
            "properties": {"issue_key": {"type": "string"}},
            "required": ["issue_key"],
        },
    )
    register_tool(
        "jira.list_projects",
        "List Jira projects visible to the connected account",
        jira_list_projects,
        input_schema={"type": "object", "properties": {}},
    )


def _register_notion_tools() -> None:
    from datetime import datetime, timedelta, timezone

    from tempa.varys.notion.client import notion_configured, query_harness_database

    if not notion_configured():
        return

    def notion_list_recent(days: int = 7) -> dict[str, Any]:
        window = max(1, min(int(days), 90))
        since = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
        pages = query_harness_database(since_iso=since)
        return {"status": "ok", "count": len(pages), "pages": pages}

    register_tool(
        "notion.list_recent",
        "List recently updated pages from the Notion harness database",
        notion_list_recent,
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
        },
    )


def register_builtin_tools() -> None:
    """Register first-party plugin tools (FR-PLUGIN-01/02)."""
    _register_memory_tools()
    _register_gmail_tools()
    _register_calendar_tools()
    _register_meet_tools()
    _register_preference_tools()
    _register_jira_tools()
    _register_notion_tools()

    from tempa.pc import tools as pc_tools

    register_tool(
        "pc.run_shell",
        "Run an allowlisted shell command",
        lambda command="": pc_tools.run_pc_tool("run_shell", command=command),
        input_schema={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    )
