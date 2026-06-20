from __future__ import annotations

import json
from typing import Any


def _format_conversation_block(recent: list[dict[str, Any]]) -> str:
    if not recent:
        return "No recent messages."
    lines: list[str] = []
    for msg in recent[-12:]:
        role = msg.get("role", "")
        text = str(msg.get("text", ""))[:200]
        if not text:
            continue
        label = "You" if role == "user" else "Tempa"
        lines.append(f"{label}: {text}")
    return "\n".join(lines) if lines else "No recent messages."


_MEETING_QA_HINTS = (
    "minutes",
    "what happened",
    "meeting summary",
    "in the meeting",
    "in meeting",
    "last meeting",
    "recent meeting",
    "give me the minutes",
    "what was discussed",
)


def _wants_meeting_archive(user_message: str) -> bool:
    lower = user_message.lower()
    return any(h in lower for h in _MEETING_QA_HINTS)


def _fetch_meeting_archive_facts() -> str:
    try:
        from tempa.meet.archive import get_latest_meeting_context

        return get_latest_meeting_context()
    except Exception:
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
    except Exception:
        return ""


def _format_pending_actions(pending: list[dict[str, Any]]) -> str:
    if not pending:
        return ""
    lines = [
        f"- {a.get('title', a.get('type', 'action'))} (id: {str(a.get('id', ''))[:8]})"
        for a in pending[:5]
    ]
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


def build_grounding_pack(
    user_message: str,
    context: dict[str, Any] | None = None,
    *,
    action_notes: list[str] | None = None,
    specialist_results: dict[str, str] | None = None,
    memory_answer: str | None = None,
    include_calendar: bool = False,
) -> dict[str, Any]:
    """Structured facts shared by WhatsApp fast reply and coordinator merge."""
    context = context or {}
    pack: dict[str, Any] = {
        "conversation_thread": "",
        "memory_answer": memory_answer or context.get("rag_context", "") or "No matching memory yet.",
        "calendar_facts": "",
        "meeting_facts": "",
        "meet_job_facts": "",
        "action_facts": list(action_notes or []),
        "active_tasks": "",
        "pending_actions": "",
    }

    try:
        from tempa.channels.whatsapp.conversation import get_recent_messages

        recent = get_recent_messages(12)
        pack["conversation_thread"] = _format_conversation_block(recent)
    except Exception:
        pack["conversation_thread"] = "No recent messages."

    if include_calendar:
        try:
            from tempa.channels.calendar.events import fetch_upcoming_summary

            pack["calendar_facts"] = fetch_upcoming_summary()
        except Exception:
            pack["calendar_facts"] = ""

    if _wants_meeting_archive(user_message):
        pack["meeting_facts"] = _fetch_meeting_archive_facts()
        if not pack["meeting_facts"]:
            pack["memory_answer"] = pack.get("memory_answer") or "No archived meeting found yet."

    pack["meet_job_facts"] = _fetch_meet_job_facts()

    if specialist_results:
        pack["action_facts"].extend(_action_facts_from_results(specialist_results))

    try:
        from tempa.core.task_store import format_active_tasks_summary

        pack["active_tasks"] = format_active_tasks_summary()
    except Exception:
        pass

    try:
        from tempa.core.pending_actions import list_pending_actions

        pending = list_pending_actions(status="pending")
        pack["pending_actions"] = _format_pending_actions(pending)
    except Exception:
        pass

    pack["user_message"] = user_message
    pack["channel"] = context.get("channel", "")
    return pack


def format_grounding_for_prompt(pack: dict[str, Any], *, owner: str = "owner") -> str:
    parts = [
        f"Conversation thread:\n{pack.get('conversation_thread', '')}",
        f"Relevant memory:\n{pack.get('memory_answer', '')}",
    ]
    if pack.get("calendar_facts"):
        parts.append(pack["calendar_facts"])
    if pack.get("meeting_facts"):
        parts.append(f"Latest meeting archive:\n{pack['meeting_facts']}")
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
