from __future__ import annotations

import json
import logging
from typing import Any

from tempa.agents.intent import (
    is_follow_up,
    wants_calendar_full,
    wants_gmail_full,
    wants_meeting_archive,
)

logger = logging.getLogger(__name__)


def _fetch_dashboard_thread(context: dict[str, Any]) -> str:
    session_id = context.get("session_id")
    if not session_id:
        return ""
    try:
        from tempa.core.chat_sessions import get_session

        session = get_session(str(session_id))
        if not session:
            return ""
        lines: list[str] = []
        for msg in (session.get("messages") or [])[-12:]:
            role = msg.get("role", "")
            text = str(msg.get("content", ""))[:500]
            if not text:
                continue
            label = "You" if role == "user" else "Tempa"
            lines.append(f"{label}: {text}")
        return "\n".join(lines) if lines else ""
    except Exception as exc:
        logger.warning("Failed to load dashboard thread: %s", exc)
        return ""


def _fetch_meet_job_facts() -> str:
    try:
        from tempa.meet.job_store import get_all_job_statuses

        statuses = get_all_job_statuses()
        if not statuses:
            return ""
        lines: list[str] = []
        for job_id, row in sorted(statuses.items(), key=lambda item: item[1].get("updated_at", ""), reverse=True)[:3]:
            status = row.get("status", "unknown")
            url = row.get("meet_url", "")
            err = row.get("error", "")
            line = f"- job {job_id[:8]}: {status}"
            if url:
                line += f" ({url})"
            if err and status == "failed":
                line += f" — {err[:120]}"
            lines.append(line)
        return "Recent Meet jobs:\n" + "\n".join(lines)
    except Exception as exc:
        logger.warning("Failed to load meet job facts: %s", exc)
        return ""


def _format_pending_actions(pending: list[dict[str, Any]]) -> str:
    if not pending:
        return ""
    lines: list[str] = []
    for action in pending[:5]:
        action_type = action.get("type", "")
        title = action.get("title", action_type or "action")
        if action_type == "email_send":
            payload = action.get("payload") or {}
            to = payload.get("to", "")
            subject = payload.get("subject", "")
            preview = str(payload.get("body") or payload.get("preview") or "")[:120]
            line = f"- Email draft to {to}: {subject}"
            if preview:
                line += f" — {preview}"
            lines.append(line)
        else:
            lines.append(f"- {title} (id: {str(action.get('id', ''))[:8]})")
    return "Pending user approval:\n" + "\n".join(lines)


def _action_facts_from_results(results: dict[str, str]) -> list[str]:
    facts: list[str] = []
    for agent, raw in results.items():
        if agent == "rag":
            continue
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("status"):
                facts.append(f"[{agent}] status={payload['status']}")
        except (json.JSONDecodeError, TypeError):
            if raw.strip():
                facts.append(f"[{agent}] {raw[:200]}")
    return facts


async def _sync_before_read(
    user_message: str,
    *,
    include_calendar: bool = False,
    context: dict[str, Any] | None = None,
) -> None:
    """Refresh snapshots when the user asks about calendar or email."""
    import asyncio

    from tempa.agents.tool_policy import include_private_grounding

    if not include_private_grounding(context):
        return

    if wants_gmail_full(user_message):
        try:
            from tempa.channels.gmail.snapshot import refresh_gmail_snapshot

            await asyncio.to_thread(refresh_gmail_snapshot)
        except Exception as exc:
            logger.warning("Gmail sync-before-read failed: %s", exc)

    if wants_calendar_full(user_message, include_calendar=include_calendar):
        try:
            from tempa.channels.calendar.sync import sync_calendar_snapshot

            await asyncio.to_thread(sync_calendar_snapshot)
        except Exception as exc:
            logger.warning("Calendar sync-before-read failed: %s", exc)


def build_grounding_pack(
    user_message: str,
    context: dict[str, Any] | None = None,
    *,
    action_notes: list[str] | None = None,
    specialist_results: dict[str, str] | None = None,
    memory_answer: str | None = None,
    include_calendar: bool = False,
    sync_first: bool = False,
) -> dict[str, Any]:
    """Structured facts shared by WhatsApp fast reply and coordinator merge."""
    context = context or {}
    channel = context.get("channel", "")
    from tempa.agents.tool_policy import include_private_grounding

    private_ok = include_private_grounding(context)
    inbound_slack = bool(context.get("inbound_slack"))
    from tempa.agents.intent import is_casual_greeting, wants_gmail_full

    casual_slack = (channel == "slack" or inbound_slack) and is_casual_greeting(user_message)
    mentions_whatsapp = "whatsapp" in user_message.lower()

    pack: dict[str, Any] = {
        "whatsapp_thread": "",
        "dashboard_thread": "",
        "gmail_compact": "",
        "gmail_full": "",
        "calendar_today": "",
        "calendar_full": "",
        "meeting_history": "",
        "meeting_facts": "",
        "live_meeting": "",
        "memory_answer": memory_answer or context.get("rag_context", "") or "No matching memory yet.",
        "meet_job_facts": "",
        "action_facts": list(action_notes or []),
        "active_tasks": "",
        "pending_actions": "",
        "gmail_last_sync_at": "",
        "calendar_last_sync_at": "",
        "slack_context": "",
        "slack_last_sync_at": "",
    }

    if private_ok and not inbound_slack and channel != "slack" and (channel == "whatsapp" or mentions_whatsapp):
        try:
            from tempa.channels.whatsapp.context import build_whatsapp_context_pack, format_whatsapp_thread_for_prompt

            wa_pack = build_whatsapp_context_pack(user_message)
            label = "Recent WhatsApp with owner" if channel == "dashboard" else "WhatsApp conversation"
            pack["whatsapp_thread"] = format_whatsapp_thread_for_prompt(wa_pack, label=label)
        except Exception as exc:
            logger.warning("WhatsApp context build failed: %s", exc)
            pack["whatsapp_thread"] = "No recent WhatsApp messages."

    if channel == "dashboard":
        pack["dashboard_thread"] = _fetch_dashboard_thread(context)

    if private_ok and not casual_slack:
        try:
            from tempa.channels.gmail.context import build_gmail_context_pack, format_gmail_context_for_prompt

            gmail_pack = build_gmail_context_pack(include_body_snippets=wants_gmail_full(user_message))
            pack["gmail_last_sync_at"] = gmail_pack.get("last_sync_at") or ""
            pack["gmail_compact"] = format_gmail_context_for_prompt(gmail_pack, compact=True)
            if wants_gmail_full(user_message):
                pack["gmail_full"] = format_gmail_context_for_prompt(gmail_pack, compact=False)
        except Exception as exc:
            logger.warning("Gmail context build failed: %s", exc)
            pack["gmail_compact"] = ""

        try:
            from tempa.channels.calendar.context import build_meeting_context_pack, format_meeting_context_for_prompt

            meeting_pack = build_meeting_context_pack()
            pack["calendar_last_sync_at"] = meeting_pack.get("last_sync_at") or ""
            pack["calendar_today"] = format_meeting_context_for_prompt(meeting_pack, full=False)
            if wants_calendar_full(user_message, include_calendar=include_calendar):
                pack["calendar_full"] = format_meeting_context_for_prompt(meeting_pack, full=True)
            live = meeting_pack.get("live_meeting") or ""
            if live:
                pack["live_meeting"] = live
        except Exception as exc:
            logger.warning("Calendar context build failed: %s", exc)
            pack["calendar_today"] = ""
            if include_calendar:
                try:
                    from tempa.channels.calendar.events import fetch_upcoming_summary

                    pack["calendar_today"] = fetch_upcoming_summary()
                except Exception as inner:
                    logger.warning("Calendar fallback summary failed: %s", inner)

    if channel == "slack" or inbound_slack:
        try:
            from tempa.channels.slack.context import build_slack_context_pack, format_slack_context_for_prompt
            from tempa.channels.slack.conversation import get_recent_messages as get_slack_thread

            slack_pack = build_slack_context_pack()
            pack["slack_last_sync_at"] = slack_pack.get("last_sync_at") or ""
            thread_lines: list[str] = []
            channel_id = str(context.get("slack_channel_id") or "")
            slack_user = str(context.get("slack_user_id") or "")
            thread_ts = str(context.get("slack_thread_ts") or "")
            if channel_id:
                for row in get_slack_thread(8, user_id=slack_user, channel_id=channel_id, thread_ts=thread_ts):
                    speaker = "You" if row.get("role") == "user" else "Tempa"
                    thread_lines.append(f"- {speaker}: {str(row.get('text') or '')[:300]}")
            if thread_lines:
                pack["slack_context"] = "This Slack thread:\n" + "\n".join(thread_lines)
            else:
                pack["slack_context"] = format_slack_context_for_prompt(slack_pack, compact=casual_slack)
        except Exception as exc:
            logger.warning("Slack context build failed: %s", exc)
            pack["slack_context"] = ""

    if private_ok and not casual_slack:
        try:
            from tempa.meet.archive import get_recent_meetings_context

            pack["meeting_history"] = get_recent_meetings_context(limit=3)
        except Exception as exc:
            logger.warning("Meeting history context failed: %s", exc)

        if wants_meeting_archive(user_message):
            try:
                from tempa.meet.archive import get_latest_meeting_context

                pack["meeting_facts"] = get_latest_meeting_context()
                if not pack["meeting_facts"]:
                    pack["memory_answer"] = pack.get("memory_answer") or "No archived meeting found yet."
            except Exception as exc:
                logger.warning("Meeting archive context failed: %s", exc)

        pack["meet_job_facts"] = _fetch_meet_job_facts()

    if specialist_results:
        pack["action_facts"].extend(_action_facts_from_results(specialist_results))

    try:
        from tempa.core.task_store import format_active_tasks_summary

        pack["active_tasks"] = format_active_tasks_summary()
    except Exception as exc:
        logger.warning("Active tasks summary failed: %s", exc)

    try:
        from tempa.core.pending_actions import list_pending_actions

        pending = list_pending_actions(status="pending")
        if private_ok:
            pack["pending_actions"] = _format_pending_actions(pending)
        else:
            pack["pending_actions"] = ""
    except Exception as exc:
        logger.warning("Pending actions load failed: %s", exc)

    pack["user_message"] = user_message
    pack["channel"] = channel

    try:
        from tempa.core.timezone import format_local_now, tz_name

        pack["local_time"] = format_local_now()
        pack["timezone"] = tz_name()
    except Exception as exc:
        logger.warning("Local time context failed: %s", exc)
        pack["local_time"] = ""
        pack["timezone"] = ""

    return pack


async def build_grounding_pack_async(
    user_message: str,
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build grounding pack after optional sync-before-read."""
    include_calendar = kwargs.pop("include_calendar", False)
    await _sync_before_read(user_message, include_calendar=include_calendar, context=context)
    return build_grounding_pack(user_message, context, include_calendar=include_calendar, **kwargs)


def format_grounding_for_prompt(pack: dict[str, Any], *, owner: str = "owner") -> str:
    parts: list[str] = []

    if pack.get("local_time"):
        parts.append(f"Owner's local time: {pack['local_time']}")

    if pack.get("whatsapp_thread"):
        parts.append(pack["whatsapp_thread"])
    if pack.get("dashboard_thread"):
        parts.append(f"Dashboard session:\n{pack['dashboard_thread']}")
    if pack.get("gmail_compact"):
        parts.append(pack["gmail_compact"])
    if pack.get("gmail_full"):
        parts.append(pack["gmail_full"])
    if pack.get("calendar_today"):
        parts.append(pack["calendar_today"])
    if pack.get("calendar_full"):
        parts.append(pack["calendar_full"])
    if pack.get("meeting_history"):
        parts.append(pack["meeting_history"])
    if pack.get("meeting_facts"):
        parts.append(f"Latest meeting archive (detail):\n{pack['meeting_facts']}")
    if pack.get("live_meeting"):
        parts.append(f"Live meeting:\n{pack['live_meeting']}")
    if pack.get("slack_context"):
        parts.append(pack["slack_context"])
    parts.append(f"Relevant memory:\n{pack.get('memory_answer', '')}")
    if pack.get("meet_job_facts"):
        parts.append(pack["meet_job_facts"])
    if pack.get("active_tasks"):
        parts.append(f"Active tasks:\n{pack['active_tasks']}")
    if pack.get("pending_actions"):
        parts.append(pack["pending_actions"])
    action_facts = pack.get("action_facts") or []
    if action_facts:
        parts.append("Actions just taken:\n" + "\n".join(f"- {n}" for n in action_facts))
    user_message = pack.get("user_message", "")
    parts.append(f"Latest message from user ({owner}): {user_message}")
    return "\n\n".join(parts)


def deterministic_reply_from_actions(pack: dict[str, Any]) -> str | None:
    """Return a factual reply from action_facts when they are the authoritative answer."""
    facts = pack.get("action_facts") or []
    if not facts:
        return None
    successes = [f for f in facts if not str(f).lower().startswith("could not")]
    failures = [f for f in facts if str(f).lower().startswith("could not")]
    if successes and failures:
        parts = ["\n".join(str(s) for s in successes), "\n".join(str(f) for f in failures)]
        return "\n\n".join(parts)
    if len(facts) == 1:
        return str(facts[0])
    return "\n\n".join(str(f) for f in facts)
