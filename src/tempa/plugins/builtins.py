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

    def calendar_create_event(
        summary: str = "",
        start_iso: str = "",
        duration_minutes: int = 60,
        with_meet: bool = True,
        attendee_emails: str = "",
    ) -> dict[str, Any]:
        from tempa.channels.calendar.events import create_calendar_event

        if not summary.strip() or not start_iso.strip():
            return {"status": "error", "reason": "summary and start_iso required"}
        try:
            start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        except ValueError:
            return {"status": "error", "reason": "start_iso must be ISO-8601"}
        emails = [e.strip() for e in (attendee_emails or "").split(",") if e.strip()]
        result = create_calendar_event(
            summary=summary.strip(),
            start=start,
            duration_minutes=int(duration_minutes) or 60,
            with_meet=bool(with_meet),
            attendee_emails=emails or None,
        )
        if not result.ok:
            return {"status": "error", "reason": result.error}
        return {
            "status": "ok",
            "summary": result.summary,
            "when": result.when,
            "meet_url": result.meet_url,
            "attendees": result.invited_attendees or [],
            "note": "Uses Tempa workspace Google Calendar, not the Slack user's personal calendar.",
        }

    def calendar_delete_by_title(title: str = "") -> dict[str, Any]:
        from tempa.channels.calendar.events import delete_calendar_events_by_title

        if not title.strip():
            return {"status": "error", "reason": "title required"}
        result = delete_calendar_events_by_title(title.strip())
        if not result.ok:
            return {"status": "error", "reason": result.error}
        return {"status": "ok", "deleted": result.deleted or []}

    register_tool(
        "calendar.list_events",
        "List upcoming Google Calendar events",
        calendar_list_events,
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
        },
    )
    register_tool(
        "calendar.create_event",
        "Create a Google Calendar event (Tempa workspace calendar). start_iso is ISO-8601.",
        calendar_create_event,
        input_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start_iso": {"type": "string"},
                "duration_minutes": {"type": "integer", "default": 60},
                "with_meet": {"type": "boolean", "default": True},
                "attendee_emails": {
                    "type": "string",
                    "description": "Comma-separated guest emails",
                },
            },
            "required": ["summary", "start_iso"],
        },
    )
    register_tool(
        "calendar.delete_by_title",
        "Delete upcoming calendar events matching a title",
        calendar_delete_by_title,
        input_schema={
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
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

    def meet_list(limit: int = 10) -> dict[str, Any]:
        import asyncio

        from tempa.meet.archive import list_meetings

        try:
            rows = asyncio.run(list_meetings(limit=max(1, min(int(limit), 50)), include_artifacts=True))
        except RuntimeError:
            # Already in an event loop — schedule on a fresh loop in a thread.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                rows = pool.submit(
                    lambda: asyncio.run(
                        list_meetings(limit=max(1, min(int(limit), 50)), include_artifacts=True)
                    )
                ).result(timeout=60)
        slim = [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "meet_url": r.get("meet_url"),
                "started_at": r.get("started_at"),
                "has_minutes": bool((r.get("artifacts") or {}).get("minutes")),
                "has_transcript": bool((r.get("artifacts") or {}).get("transcript")),
            }
            for r in rows
        ]
        return {"status": "ok", "count": len(slim), "meetings": slim}

    def meet_get_minutes(meeting_id: str = "") -> dict[str, Any]:
        import asyncio

        from tempa.meet.archive import list_meetings

        mid = (meeting_id or "").strip()
        if not mid:
            return {"status": "error", "reason": "meeting_id required"}

        def _load() -> dict[str, Any]:
            rows = asyncio.run(list_meetings(limit=200, include_artifacts=True))
            for r in rows:
                if str(r.get("id") or "") == mid:
                    return {
                        "status": "ok",
                        "meeting_id": mid,
                        "title": r.get("title"),
                        "minutes": r.get("minutes") or {},
                        "artifacts": r.get("artifacts") or {},
                    }
            return {"status": "error", "reason": f"meeting {mid} not found"}

        try:
            return _load()
        except RuntimeError:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_load).result(timeout=60)

    def meet_generate_minutes_from_text(transcript: str = "", source_name: str = "transcript.txt") -> dict[str, Any]:
        """On-demand minutes via Groq backend (background STT/minutes engine)."""
        import asyncio

        from tempa.meet.archive import generate_minutes_from_transcript

        text = (transcript or "").strip()
        if not text:
            return {"status": "error", "reason": "transcript required"}

        async def _run() -> dict[str, Any]:
            return await generate_minutes_from_transcript(text, source_name=source_name or "transcript.txt")

        try:
            result = asyncio.run(_run())
        except RuntimeError:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(lambda: asyncio.run(_run())).result(timeout=180)
        return {"status": "ok", "minutes": result}

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
    register_tool(
        "meet.list",
        "List recent Meet archives (auto-captured notes use Groq STT in the background)",
        meet_list,
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
    )
    register_tool(
        "meet.get_minutes",
        "Fetch stored minutes/artifacts for a meeting id from Tempa archives",
        meet_get_minutes,
        input_schema={
            "type": "object",
            "properties": {"meeting_id": {"type": "string"}},
            "required": ["meeting_id"],
        },
    )
    register_tool(
        "meet.generate_minutes",
        "Generate meeting minutes from transcript text (uses Groq minutes backend)",
        meet_generate_minutes_from_text,
        input_schema={
            "type": "object",
            "properties": {
                "transcript": {"type": "string"},
                "source_name": {"type": "string", "default": "transcript.txt"},
            },
            "required": ["transcript"],
        },
    )


def _register_preference_tools() -> None:
    from tempa.rag.procedural import add_fact, add_preference, list_durable, list_preferences

    def memory_add_preference(rule: str = "", user_id: str = "") -> dict[str, Any]:
        tags = [f"user:{user_id.strip()}"] if user_id.strip() else []
        return add_preference(rule, source="tempa_agent", tags=tags or None)

    def memory_add_fact(text: str = "", kind: str = "fact") -> dict[str, Any]:
        return add_fact(text, kind=kind or "fact", source="tempa_agent", tags=["scope:team"])

    register_tool(
        "memory.add_preference",
        "Store a user preference or procedural rule (pass user_id to scope to that person)",
        memory_add_preference,
        input_schema={
            "type": "object",
            "properties": {
                "rule": {"type": "string"},
                "user_id": {"type": "string"},
            },
            "required": ["rule"],
        },
    )
    register_tool(
        "memory.list_preferences",
        "List stored user preferences",
        lambda: {"preferences": list_preferences()},
        input_schema={"type": "object", "properties": {}},
    )
    register_tool(
        "memory.add_fact",
        "Store a durable org/team fact, person, project, or decision",
        memory_add_fact,
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "kind": {
                    "type": "string",
                    "description": "fact|person|project|decision",
                },
            },
            "required": ["text"],
        },
    )
    register_tool(
        "memory.list_durable",
        "List durable memory items (preferences, facts, people, projects, decisions)",
        lambda kind="": {"items": list_durable(kinds=[kind] if kind else None)},
        input_schema={
            "type": "object",
            "properties": {"kind": {"type": "string"}},
        },
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


def _register_coolify_tools() -> None:
    from tempa.channels.coolify.client import (
        app_url,
        coolify_configured,
        create_application,
        find_app_by_repo,
        list_applications,
        normalize_git_repository,
        parse_env_block,
        poll_deployment,
        set_envs,
        trigger_deploy,
        get_application,
    )

    def coolify_list_apps() -> dict[str, Any]:
        if not coolify_configured():
            return {"status": "error", "reason": "Coolify not connected"}
        apps = list_applications()
        slim = [
            {
                "uuid": a.get("uuid"),
                "name": a.get("name"),
                "git_repository": a.get("git_repository"),
                "fqdn": a.get("fqdn"),
                "status": a.get("status"),
            }
            for a in apps
        ]
        return {"status": "ok", "count": len(slim), "applications": slim}

    def coolify_status(git_repository: str = "") -> dict[str, Any]:
        if not coolify_configured():
            return {"status": "error", "reason": "Coolify not connected"}
        repo = normalize_git_repository(git_repository)
        if not repo:
            return {"status": "error", "reason": "git_repository required"}
        app = find_app_by_repo(repo)
        if not app:
            return {"status": "error", "reason": f"No Coolify app for {repo}"}
        return {
            "status": "ok",
            "application": {
                "uuid": app.get("uuid"),
                "name": app.get("name"),
                "git_repository": app.get("git_repository"),
                "url": app_url(app),
                "status": app.get("status"),
            },
        }

    def coolify_set_envs(git_repository: str = "", env_text: str = "") -> dict[str, Any]:
        if not coolify_configured():
            return {"status": "error", "reason": "Coolify not connected"}
        repo = normalize_git_repository(git_repository)
        envs = parse_env_block(env_text)
        if not repo or not envs:
            return {"status": "error", "reason": "git_repository and KEY=value env_text required"}
        app = find_app_by_repo(repo)
        if not app:
            return {"status": "error", "reason": f"No Coolify app for {repo}"}
        set_envs(str(app["uuid"]), envs)
        return {"status": "ok", "keys": list(envs.keys()), "uuid": app.get("uuid")}

    def coolify_deploy(
        git_repository: str = "",
        git_branch: str = "main",
        private: bool = False,
        ports_exposes: str = "3000",
        env_text: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        if not coolify_configured():
            return {"status": "error", "reason": "Coolify not connected"}
        repo = normalize_git_repository(git_repository)
        if not repo:
            return {"status": "error", "reason": "git_repository required"}
        envs = parse_env_block(env_text)
        existing = find_app_by_repo(repo)
        if existing:
            uuid = str(existing.get("uuid") or "")
            if envs:
                set_envs(uuid, envs)
            dep_uuid = trigger_deploy(uuid, force=force)
            dep = poll_deployment(dep_uuid)
            app = get_application(uuid)
            return {
                "status": "ok",
                "action": "redeploy",
                "deployment_status": dep.get("status"),
                "url": app_url(app),
                "uuid": uuid,
            }
        app = create_application(
            git_repository=repo,
            git_branch=git_branch or "main",
            private=bool(private),
            ports_exposes=ports_exposes or "3000",
            envs=envs or None,
            instant_deploy=False,
        )
        uuid = str(app.get("uuid") or "")
        if envs:
            set_envs(uuid, envs)
        dep_uuid = trigger_deploy(uuid, force=force)
        dep = poll_deployment(dep_uuid)
        app = get_application(uuid)
        return {
            "status": "ok",
            "action": "create",
            "deployment_status": dep.get("status"),
            "url": app_url(app),
            "uuid": uuid,
        }

    register_tool(
        "coolify.list_apps",
        "List applications on the connected Coolify instance",
        coolify_list_apps,
        input_schema={"type": "object", "properties": {}},
    )
    register_tool(
        "coolify.status",
        "Get Coolify app status/URL by GitHub repo (owner/repo)",
        coolify_status,
        input_schema={
            "type": "object",
            "properties": {"git_repository": {"type": "string"}},
            "required": ["git_repository"],
        },
    )
    register_tool(
        "coolify.set_envs",
        "Set Coolify app env vars from KEY=value lines (never echo values)",
        coolify_set_envs,
        input_schema={
            "type": "object",
            "properties": {
                "git_repository": {"type": "string"},
                "env_text": {"type": "string"},
            },
            "required": ["git_repository", "env_text"],
        },
    )
    register_tool(
        "coolify.deploy",
        "Create or redeploy a GitHub repo on Coolify and return the live URL",
        coolify_deploy,
        input_schema={
            "type": "object",
            "properties": {
                "git_repository": {"type": "string"},
                "git_branch": {"type": "string", "default": "main"},
                "private": {"type": "boolean", "default": False},
                "ports_exposes": {"type": "string", "default": "3000"},
                "env_text": {"type": "string"},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["git_repository"],
        },
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
    _register_coolify_tools()
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
