from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

from tempa.agents.config import model_category_for_agent
from tempa.channels.calendar.ingest import ingest_calendar_event
from tempa.channels.calendar.oauth import load_calendar_client
from tempa.channels.gmail.compose import (
    extract_all_recipients,
    finalize_beautiful_email,
    resolve_email_recipient,
    validate_recipient_email,
)
from tempa.channels.gmail.ingest import ingest_gmail_message, message_to_text
from tempa.channels.gmail.oauth import load_gmail_client
from tempa.channels.gmail.query import extract_gmail_query
from tempa.channels.gmail.session_state import record_gmail_action
from tempa.channels.gmail.whatsapp_format import format_whatsapp_email_list
from tempa.channels.whatsapp.outbound import send_whatsapp_message
from tempa.channels.whatsapp.webhook import get_recent_messages
from tempa.core.events import event_bus
from tempa.pc.tools import run_pc_tool
from tempa.rag.agent import run_rag_agent
from tempa.rag.ingest import ingest_text, search_memory
from tempa.router.groq_router import get_router


def _extract_meet_url(text: str) -> str | None:
    match = re.search(r"https://meet\.google\.com/[a-z0-9\-]+", text, re.I)
    return match.group(0) if match else None


async def run_channel_agent(task: str, context: dict[str, Any]) -> str:
    await event_bus.publish_json("channel", "start", task[:120])
    number = context.get("whatsapp_number", "")
    if "send" in task.lower() and number:
        reply = context.get("draft_reply") or context.get("coordinator_reply", "Tempa acknowledgement.")
        if context.get("inbound_whatsapp"):
            return json.dumps({"draft": reply}, ensure_ascii=False)
        from tempa.channels.contacts.sync import resolve_recipient

        resolved = resolve_recipient(number) if number and "@" not in number else {"phone": number}
        target = resolved.get("phone") or number
        result = await send_whatsapp_message(target, reply, source_channel="coordinator")
        return json.dumps(result, ensure_ascii=False)
    recent = get_recent_messages(5)
    return json.dumps({"recent_messages": recent}, ensure_ascii=False)


def _is_email_task(text: str) -> bool:
    lower = text.lower()
    if any(k in lower for k in ("gmail", "inbox", "email", "e-mail")):
        return True
    if "mail" in lower and not any(k in lower for k in ("whatsapp", "meet")):
        return True
    return False


def _is_send_email_task(text: str) -> bool:
    lower = text.lower()
    if not _is_email_task(text):
        return False
    return any(k in lower for k in ("send", "compose", "write", "reply", "forward", "draft"))


async def _compose_email_draft(task: str, context: dict[str, Any]) -> dict[str, str]:
    import asyncio

    router = get_router()
    rag = context.get("rag_context", "")
    contacts_hint = ""
    contact_hint: dict[str, str] = {}
    gmail_hint: dict[str, str] = {}
    user_message = str(context.get("user_message", "")).strip()

    from tempa.channels.gmail.recipients import extract_recipient_name, lookup_email_by_name_in_gmail

    recipient_name = extract_recipient_name(user_message) or extract_recipient_name(task)
    has_explicit_email = bool(
        extract_all_recipients(user_message) or extract_all_recipients(task)
    )
    if recipient_name and not has_explicit_email:
        gmail_hint = await asyncio.to_thread(lookup_email_by_name_in_gmail, recipient_name)
        if gmail_hint.get("email"):
            contacts_hint = (
                f"\nUse this real recipient found in Gmail history: {gmail_hint['email']}"
                f" ({gmail_hint.get('name', recipient_name)}). "
                "Never use example.com or placeholder emails."
            )

    if not gmail_hint.get("email"):
        try:
            from tempa.channels.contacts.sync import resolve_recipient

            for query in (recipient_name, user_message, task):
                if not query.strip():
                    continue
                hint = resolve_recipient(query)
                if hint.get("email"):
                    contact_hint = hint
                    contacts_hint = (
                        f"\nUse this real recipient from contacts: {hint['email']}"
                        f" ({hint.get('name', '')}). Never use example.com or placeholder emails."
                    )
                    break
        except Exception:
            pass
    prompt = (
        "Extract email fields from the user request. Return JSON only: "
        '{"to": "real recipient email from the request or contacts", "subject": "...", '
        '"body": "main message paragraphs (plain text, no sign-off)", '
        '"eyebrow_label": "short tag e.g. UPDATE or MESSAGE", '
        '"closing_text": "optional warm closing line", '
        '"signature": "e.g. Warm regards, Name"}. '
        "Never use example.com, test.com, or placeholder addresses. "
        "If the recipient is unclear, leave \"to\" empty. "
        "Do NOT return body_html — HTML layout is added automatically. "
        "Write polished, professional copy."
        + contacts_hint
        + "\n"
        f"User request: {task}\n"
        f"Context: {rag[:2000] if rag else 'none'}"
    )
    response = router.chat_completion(
        category="text",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=1536,
        temperature=0.3,
    )
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)
    to = resolve_email_recipient(
        task=task,
        user_message=user_message,
        llm_to=str(payload.get("to", "")).strip(),
        contact_hint=contact_hint,
        gmail_hint=gmail_hint,
    )
    draft = finalize_beautiful_email(
        {
            "to": to,
            "subject": str(payload.get("subject", "")).strip() or "Hello from Tempa",
            "body": str(payload.get("body", "")).strip(),
            "eyebrow_label": str(payload.get("eyebrow_label", "")).strip(),
            "closing_text": str(payload.get("closing_text", "")).strip(),
            "signature": str(payload.get("signature", "")).strip(),
        }
    )
    valid, recipient_error = validate_recipient_email(draft.get("to", ""))
    if not valid:
        if recipient_name and not has_explicit_email:
            recipient_error = (
                f"Could not find a real email for '{recipient_name}' in your Gmail history or contacts. "
                "Try including their email address directly."
            )
        return {"to": "", "subject": draft["subject"], "body": "", "body_html": "", "error": recipient_error}
    return {
        "to": draft["to"],
        "subject": draft["subject"],
        "body": draft["body"],
        "body_html": draft["body_html"],
    }


def _gmail_search_payload(
    messages: list[Any],
    *,
    query: str,
    used_fallback_query: str = "",
) -> dict[str, Any]:
    payload = [
        {
            "id": m.id,
            "subject": m.subject,
            "from": m.sender,
            "date": m.date,
            "snippet": m.snippet,
            "unread": "UNREAD" in (m.label_ids or []),
            "preview": message_to_text(m)[:500],
        }
        for m in messages
    ]
    result: dict[str, Any] = {"query": query, "count": len(payload), "messages": payload}
    if used_fallback_query:
        result["used_fallback_query"] = used_fallback_query
    return result


async def run_gmail_agent(task: str, context: dict[str, Any]) -> str:
    import logging

    logger = logging.getLogger(__name__)
    await event_bus.publish_json("gmail", "start", task[:120])
    client = load_gmail_client()
    if client is None:
        return "Gmail not connected. Connect Gmail in the Connections panel first."

    user_message = context.get("user_message", task)
    skip_ingest = bool(context.get("inbound_whatsapp") or context.get("skip_ingest"))

    if _is_send_email_task(task) or _is_send_email_task(user_message):
        draft = await _compose_email_draft(task, context)
        if draft.get("error"):
            err = {
                "status": "error",
                "error": draft["error"],
                "to": draft.get("to", ""),
            }
            record_gmail_action(err)
            return json.dumps(err, ensure_ascii=False)
        if not draft.get("to") or not (draft.get("body") or draft.get("body_html")):
            err = {
                "status": "error",
                "error": "Could not determine a real recipient email or message body",
                "to": draft.get("to", ""),
            }
            record_gmail_action(err)
            return json.dumps(err, ensure_ascii=False)

        from tempa.core.notifications import notify
        from tempa.core.pending_actions import create_pending_action

        action = create_pending_action(
            "email_send",
            draft,
            source_channel=context.get("channel", "coordinator"),
            risk_level="high",
            title=f"Email to {draft.get('to', '')}",
        )
        await notify(
            "pending_action",
            title="Email ready for review",
            body=f"To: {draft.get('to')} — {draft.get('subject', '')}",
            pending_action_id=action["id"],
        )
        result = {
            "status": "pending",
            "pending_action_id": action["id"],
            "to": draft.get("to"),
            "subject": draft.get("subject"),
            "preview": (draft.get("body") or "")[:500],
        }
        record_gmail_action(result)
        from tempa.channels.whatsapp.action_state import record_action

        record_action("gmail", result)
        return json.dumps(result, ensure_ascii=False)

    recent_context = context.get("recent_user_messages") or []
    if not recent_context and context.get("inbound_whatsapp"):
        recent_context = [
            m.get("text", "")
            for m in get_recent_messages(8)
            if m.get("role") == "user"
        ]

    plan = extract_gmail_query(task, user_message, recent_context=recent_context)
    search = client.search_message_previews if skip_ingest else client.search_messages
    used_fallback = ""

    try:
        messages = search(plan.primary, max_results=10)
        query = plan.primary
        for fallback in plan.fallbacks:
            if messages:
                break
            used_fallback = fallback
            messages = search(fallback, max_results=10)
            query = fallback
    except Exception as exc:
        return f"Gmail search failed: {exc}"

    if not messages:
        return json.dumps(
            {
                "messages": [],
                "query": plan.primary,
                "count": 0,
                "summary": "No messages found.",
                "tried_fallbacks": list(plan.fallbacks),
            },
            ensure_ascii=False,
        )

    if not skip_ingest:
        full_messages = client.get_messages([m.id for m in messages])
        for msg in full_messages:
            try:
                ingest_gmail_message(msg, tags=["fetch"])
            except Exception:
                logger.exception("Gmail message ingest failed for %s", msg.id)

    payload = _gmail_search_payload(
        messages,
        query=query,
        used_fallback_query=used_fallback if used_fallback and used_fallback != plan.primary else "",
    )
    if not skip_ingest:
        try:
            ingest_text(
                json.dumps(payload, ensure_ascii=False),
                tool="gmail",
                source=f"search:{query}",
                tags=["search"],
            )
        except Exception:
            logger.exception("Gmail search batch ingest failed")
    return json.dumps(payload, ensure_ascii=False)


async def run_calendar_agent(task: str, context: dict[str, Any]) -> str:
    await event_bus.publish_json("calendar", "start", task[:120])
    from datetime import datetime, timedelta, timezone

    from tempa.channels.calendar.events import apply_calendar_actions_from_message

    user_message = str(context.get("user_message") or task)
    recent = context.get("recent_user_messages") or []
    actions = apply_calendar_actions_from_message(user_message, recent_texts=recent)

    client = load_calendar_client()
    if client is None and actions.get("action") == "none":
        return "Google Calendar not connected."

    upcoming: list[dict[str, str | None]] = []
    if client is not None:
        now = datetime.now(timezone.utc)
        events = client.list_upcoming_events(
            calendar_id="primary",
            time_min=now,
            time_max=now + timedelta(days=7),
        )
        meet_events = [e for e in events if e.meet_url]
        for e in meet_events[:10]:
            ingest_calendar_event(e)
        upcoming = [
            {
                "summary": e.summary,
                "start": e.start.isoformat(),
                "meet_url": e.meet_url,
            }
            for e in meet_events[:10]
        ]
        if upcoming:
            ingest_text(json.dumps(upcoming), tool="calendar", source="upcoming", tags=["poll"])

    return json.dumps({"actions": actions, "upcoming": upcoming}, ensure_ascii=False)


async def run_rag_agent_task(task: str, context: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    await event_bus.publish_json("rag", "retrieve", task[:120])
    query = context.get("user_message", task)
    mode = "fast" if context.get("channel") == "whatsapp" else "full"
    try:
        if mode == "full":
            from tempa.rag.agent import run_rag_agent_with_sources

            return run_rag_agent_with_sources(query, mode=mode)
        from tempa.rag.retriever import retrieve_with_sources

        text, sources = retrieve_with_sources(query, top_k=5)
        if not text.strip():
            return "No relevant memory found.", []
        from tempa.rag.graph import GENERATE_PROMPT, GRADE_PROMPT, _llm_text

        grade_prompt = GRADE_PROMPT.format(question=query, context=text)
        router = get_router()
        response = router.chat_completion(
            category="reasoning",
            messages=[{"role": "user", "content": grade_prompt + "\nReply with only yes or no."}],
            max_tokens=16,
        )
        score = (response.choices[0].message.content or "no").strip().lower()
        if not score.startswith("y"):
            return "No relevant memory found.", []
        answer_prompt = GENERATE_PROMPT.format(question=query, context=text)
        answer = _llm_text([{"role": "user", "content": answer_prompt}], category="text")
        return answer, sources
    except Exception:
        results = search_memory(query, top_k=5)
        if not results:
            return "No relevant memory found.", []
        sources = [
            {
                "label": f"{r['metadata'].get('tool', '?')}/{r['metadata'].get('source', '?')}",
                "tool": r["metadata"].get("tool"),
                "source": r["metadata"].get("source"),
                "title": r["metadata"].get("title") or "",
                "timestamp": r["metadata"].get("timestamp") or "",
                "score": r.get("score"),
            }
            for r in results
        ]
        return "\n\n".join(r["content"] for r in results), sources


async def run_plugin_agent(task: str, context: dict[str, Any]) -> str:
    await event_bus.publish_json("plugin", "start", task[:120])
    from tempa.plugins.registry import list_tools, run_tool

    tools = list_tools()
    if not tools:
        return json.dumps({"status": "error", "reason": "No plugin tools registered"})

    groq_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"].replace(".", "_"),
                "description": t["description"],
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]
    name_map = {t["name"].replace(".", "_"): t["name"] for t in tools}

    router = get_router()
    prompt = (
        f"Select and call the best plugin tool for this task.\n"
        f"Task: {task}\n"
        f"User message: {context.get('user_message', '')}\n"
        f"Memory context: {str(context.get('rag_context', ''))[:1500]}"
    )
    response = router.chat_completion(
        category=model_category_for_agent("plugin", "tool_use"),
        messages=[{"role": "user", "content": prompt}],
        tools=groq_tools,
        max_tokens=512,
    )
    msg = response.choices[0].message
    if not msg.tool_calls:
        return json.dumps({"status": "error", "reason": "No plugin tool selected"})
    results: list[dict[str, Any]] = []
    for tc in msg.tool_calls:
        tool_name = name_map.get(tc.function.name, tc.function.name.replace("_", "."))
        args = json.loads(tc.function.arguments or "{}")
        results.append(run_tool(tool_name, **args))
    await event_bus.publish_json("plugin", "completed", task[:80])
    return json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False)


async def run_meet_agent(task: str, context: dict[str, Any]) -> str:
    await event_bus.publish_json("meet", "start", task[:120])
    from tempa.channels.whatsapp.action_state import record_action
    from tempa.meet.service import schedule_meeting_join

    meet_url = context.get("meet_url") or _extract_meet_url(task) or _extract_meet_url(context.get("user_message", ""))
    if not meet_url:
        return "No Google Meet URL found in request."
    title = context.get("title") or context.get("user_message", "") or task
    try:
        meeting_id = schedule_meeting_join(meet_url, title=title)
    except RuntimeError as exc:
        record_action("meet", {"status": "failed", "meet_url": meet_url, "error": str(exc)})
        return str(exc)
    record_action("meet", {"status": "queued", "meeting_id": meeting_id, "meet_url": meet_url})
    try:
        ingest_text(
            f"Meet join started for {meet_url}",
            tool="meet",
            source=meeting_id,
            meet_link=meet_url,
            title=title,
            tags=["scheduled"],
        )
    except Exception:
        logger.warning("Meet agent RAG ingest failed (join still queued)", exc_info=True)
    return f"Meet Agent started worker {meeting_id} for {meet_url}"


_PC_GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run an allowlisted shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read lines from a file on the PC",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start": {"type": "integer"},
                    "count": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file on the PC",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open an application by name",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": "Close an application by name",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory (requires user confirmation)",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "Delete a file or empty directory (requires user confirmation)",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_file_transfer",
            "description": "Prepare sending a file to user's phone over WiFi (requires confirmation)",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]


def _run_pc_tool_from_groq(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from tempa.pc.tools import request_pc_confirmation, run_pc_tool

    mapping = {
        "run_shell": "run_shell",
        "read_file": "read_file",
        "write_file": "write_file",
        "open_app": "open_app",
        "close_app": "close_app",
        "create_directory": "create_directory",
        "delete_path": "delete_path",
        "prepare_file_transfer": "prepare_file_transfer",
    }
    tool = mapping.get(name)
    if not tool:
        return {"status": "error", "msg": f"Unknown PC tool: {name}"}
    if tool in ("write_file", "create_directory", "delete_path", "prepare_file_transfer"):
        return request_pc_confirmation(tool, **arguments)
    return run_pc_tool(tool, **arguments)


async def run_pc_agent(task: str, context: dict[str, Any]) -> str:
    await event_bus.publish_json("pc", "start", task[:120])
    router = get_router()
    try:
        response = router.chat_completion(
        category=model_category_for_agent("pc", "tool_use"),
        messages=[{"role": "user", "content": task}],
        tools=_PC_GROQ_TOOLS,
        max_tokens=512,
    )
        msg = response.choices[0].message
        if msg.tool_calls:
            results: list[dict[str, Any]] = []
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                results.append(_run_pc_tool_from_groq(tc.function.name, args))
            await event_bus.publish_json("pc", "completed", task[:80])
            return json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False)
    except Exception:
        pass

    lower = task.lower()
    if "close" in lower:
        name = context.get("app_name", "Visual Studio Code")
        for token in ("vscode", "code", "chrome", "firefox"):
            if token in lower:
                name = {"vscode": "Visual Studio Code", "code": "Visual Studio Code"}.get(token, token.title())
        result = run_pc_tool("close_app", name=name)
    elif "open" in lower and ("code" in lower or "vscode" in lower):
        result = run_pc_tool("open_app", name="Visual Studio Code")
    elif "create" in lower and ".md" in lower:
        path = context.get("pc_path", str(get_settings_safe().tempa_data_dir / "project_plan.md"))
        from tempa.pc.tools import request_pc_confirmation

        result = request_pc_confirmation(
            "write_file", path=path, content="# Project Plan\n\nCreated by Tempa PC Agent.\n"
        )
    elif "read" in lower and context.get("pc_path"):
        result = run_pc_tool("read_file", path=context["pc_path"])
    else:
        result = run_pc_tool("run_shell", command="pwd")
    await event_bus.publish_json("pc", "completed", task[:80])
    return json.dumps(result, ensure_ascii=False)


def get_settings_safe():
    from tempa.settings import get_settings

    return get_settings()


def _heuristic_subtasks(user_message: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = [{"agent": "rag", "task": user_message}]
    if _extract_meet_url(user_message):
        tasks.append({"agent": "meet", "task": "join meeting"})
    lower = user_message.lower()
    if _is_email_task(user_message):
        tasks.append({"agent": "gmail", "task": user_message})
    elif any(k in lower for k in ("whatsapp", "message", "remind", "notify")):
        tasks.append({"agent": "channel", "task": user_message})
    elif any(k in lower for k in ("send", "message")) and not _is_email_task(user_message):
        tasks.append({"agent": "channel", "task": user_message})
    if any(k in lower for k in ("calendar", "meeting", "schedule")):
        tasks.append({"agent": "calendar", "task": user_message})
    if any(k in lower for k in ("open", "file", "shell", "vscode", "create")):
        tasks.append({"agent": "pc", "task": user_message})
    return tasks


def _is_short_follow_up(text: str) -> bool:
    lower = text.lower().strip()
    if len(lower) > 80:
        return False
    return any(
        hint in lower
        for hint in (
            "what",
            "which",
            "when",
            "where",
            "who",
            "name",
            "kaun",
            "kya",
            "kab",
            "?",
        )
    )


def _count_intent_signals(user_message: str) -> int:
    lower = user_message.lower()
    signals = 0
    if _extract_meet_url(user_message) or "meet.google.com" in lower:
        signals += 1
    if _is_email_task(user_message):
        signals += 1
    if any(k in lower for k in ("whatsapp", "message", "notify", "remind")):
        signals += 1
    if any(k in lower for k in ("calendar", "meeting", "schedule")):
        signals += 1
    if any(k in lower for k in ("open", "file", "shell", "vscode", "create")):
        signals += 1
    return signals


def _heuristic_has_conflicts(tasks: list[dict[str, Any]]) -> bool:
    agents = {t.get("agent") for t in tasks}
    return "gmail" in agents and "channel" in agents


def _needs_llm_planning(user_message: str, heuristic: list[dict[str, Any]], context: dict[str, Any]) -> bool:
    if _count_intent_signals(user_message) >= 2:
        return True
    if _heuristic_has_conflicts(heuristic):
        return True
    recent = context.get("recent_user_messages") or []
    if _is_short_follow_up(user_message) and recent:
        return True
    if len(user_message) >= 280 or len(heuristic) > 2:
        return True
    return False


_PLANNER_FEW_SHOT = """
Example 1:
User: "Prepare for my 2pm Google Meet and remind the team on WhatsApp."
{"subtasks": [
  {"agent": "rag", "task": "Retrieve context about the 2pm meeting", "depends_on": []},
  {"agent": "calendar", "task": "Find the 2pm meeting details and Meet link", "depends_on": []},
  {"agent": "meet", "task": "Queue join for the 2pm Google Meet", "depends_on": []},
  {"agent": "channel", "task": "Draft WhatsApp reminder for the team", "depends_on": []}
]}

Example 2:
User: "join https://meet.google.com/abc-defg-hij and message the team"
{"subtasks": [
  {"agent": "rag", "task": "Retrieve team contact context", "depends_on": []},
  {"agent": "meet", "task": "Join the Google Meet at the provided link", "depends_on": []},
  {"agent": "channel", "task": "Send WhatsApp message to the team", "depends_on": []}
]}
"""


def plan_subtasks(user_message: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from tempa.plugins.registry import list_tools

    context = context or {}
    heuristic = _heuristic_subtasks(user_message)
    plugin_names = [t["name"] for t in list_tools()]
    lower_msg = user_message.lower()
    for plugin_name in plugin_names:
        short = plugin_name.split(".")[-1]
        if short in lower_msg or plugin_name in lower_msg:
            if not any(t.get("agent") == "plugin" for t in heuristic):
                heuristic.append({"agent": "plugin", "task": user_message})
            break
    if not _needs_llm_planning(user_message, heuristic, context):
        return heuristic

    router = get_router()
    context_lines: list[str] = []
    if context.get("channel"):
        context_lines.append(f"Channel: {context['channel']}")
    if context.get("active_tasks"):
        context_lines.append(f"Active tasks: {context['active_tasks']}")
    rag_preview = context.get("rag_context", "")
    if rag_preview:
        context_lines.append(f"Memory preview: {str(rag_preview)[:500]}")
    recent = context.get("recent_user_messages") or []
    if recent:
        context_lines.append("Recent user messages: " + " | ".join(recent[-4:]))
    context_block = "\n".join(context_lines)

    prompt = (
        "Decompose the user request into specialist subtasks for agents: "
        "meet, channel, calendar, gmail, rag, pc, plugin.\n"
        "Rules:\n"
        "- Always include a rag subtask for context retrieval.\n"
        "- Only include agents that have a concrete task.\n"
        '- Return JSON only: {"subtasks": [{"agent": "...", "task": "...", "depends_on": []}]}\n'
        f"{_PLANNER_FEW_SHOT}\n"
        f"{context_block + chr(10) if context_block else ''}"
        f"User message: {user_message}"
    )
    try:
        response = router.chat_completion(
            category="reasoning",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=512,
            temperature=0.1,
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and "tasks" in payload:
            return payload["tasks"]
        if isinstance(payload, dict) and "subtasks" in payload:
            return payload["subtasks"]
    except Exception:
        pass
    return heuristic


def _calendar_action_reply(calendar_result: str) -> str | None:
    """Short-circuit when calendar create/delete/invite actually ran."""
    try:
        payload = json.loads(calendar_result)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    actions = payload.get("actions")
    if not isinstance(actions, dict):
        return None
    if actions.get("action") == "none":
        return None
    parts = list(actions.get("successes") or []) + list(actions.get("failures") or [])
    if parts:
        return "\n\n".join(parts)
    if not actions.get("ok"):
        return f"Calendar action failed: {actions.get('error', 'unknown error')}"
    return None


def _whatsapp_gmail_reply(gmail_result: str) -> str | None:
    """Short-circuit WhatsApp replies for clear Gmail outcomes."""
    lower = gmail_result.lower()
    if "not connected" in lower:
        return "Gmail isn't connected yet. Open Tempa → Connections, connect Gmail, then ask again."
    try:
        payload = json.loads(gmail_result)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if status == "sent":
        to = payload.get("to") or payload.get("message_id", "recipient")
        kind = "HTML email" if payload.get("html") else "Email"
        return f"{kind} sent to {to}."
    if status == "pending":
        return (
            f"I've prepared an email to {payload.get('to', 'the recipient')}. "
            f"Open Tempa to review and send (pending id: {payload.get('pending_action_id', '')[:8]}…)."
        )
    if status == "blocked":
        reason = str(payload.get("reason") or "").strip() or "blocked by safety screen"
        return f"Couldn't send that email: {reason}"
    if status == "error":
        reason = str(payload.get("reason") or payload.get("error") or "").strip() or "unknown error"
        return f"Email failed: {reason}"
    if payload.get("error"):
        return f"Email failed: {payload['error']}"
    if "messages" in payload or "count" in payload:
        return format_whatsapp_email_list(payload)
    return None


def _build_merge_prompt(
    user_message: str,
    results: dict[str, str],
    context: dict[str, Any],
    sources: list[dict[str, Any]],
) -> tuple[str, Any, list[dict[str, Any]]]:
    """Build merge prompt and grounding pack. Returns (prompt, pack, sources)."""
    from tempa.agents.grounding import build_grounding_pack, format_grounding_for_prompt

    channel = context.get("channel", "")

    pack = build_grounding_pack(
        user_message,
        context,
        specialist_results=results,
        memory_answer=context.get("rag_context", ""),
        include_calendar=any(k in user_message.lower() for k in ("calendar", "meeting", "schedule", "event")),
    )
    grounding_block = format_grounding_for_prompt(
        pack,
        owner=context.get("whatsapp_number", "owner"),
    )

    citation_block = ""
    if sources:
        labels = [s.get("label", "") for s in sources[:5] if s.get("label")]
        if labels:
            citation_block = (
                "Cite sources inline using [tool/source] labels when referencing memory: "
                + ", ".join(labels)
                + "\n"
            )

    style = (
        "Reply in 1–4 short sentences, warm and direct — this is WhatsApp.\n"
        if channel == "whatsapp"
        else "Merge specialist outputs into one concise user-facing reply.\n"
    )
    prompt = (
        f"{style}"
        f"{citation_block}"
        f"Grounding facts:\n{grounding_block}\n\n"
        f"Agent results JSON: {json.dumps(results, ensure_ascii=False)}"
    )
    if context.get("procedural_memory"):
        prompt = f"{context['procedural_memory']}\n\n{prompt}"
    return prompt, pack, sources


async def merge_results_stream(
    user_message: str,
    results: dict[str, str],
    context: dict[str, Any] | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    from tempa.router.verifier import verify_reply

    context = context or {}
    router = get_router()
    channel = context.get("channel", "")
    sources: list[dict[str, Any]] = list(context.get("rag_sources") or [])

    if channel == "whatsapp" and "gmail" in results:
        short = _whatsapp_gmail_reply(results["gmail"])
        if short:
            if on_token:
                await on_token(short)
            return short, sources

    if "calendar" in results:
        short = _calendar_action_reply(results["calendar"])
        if short:
            if on_token:
                await on_token(short)
            return short, sources

    prompt, pack, sources = _build_merge_prompt(user_message, results, context, sources)
    parts: list[str] = []
    async for delta in router.chat_completion_stream(
        category=model_category_for_agent("channel", "text"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400 if channel == "whatsapp" else 1024,
        temperature=0.2 if channel == "whatsapp" else 0.3,
    ):
        parts.append(delta)
        if on_token:
            await on_token(delta)

    reply = "".join(parts) or json.dumps(results, ensure_ascii=False)

    if channel == "whatsapp":
        ok, verified = verify_reply(reply, pack)
        if not ok:
            return verified, sources
    return reply, sources


async def merge_results(
    user_message: str,
    results: dict[str, str],
    context: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    return await merge_results_stream(user_message, results, context, on_token=None)
