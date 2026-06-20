from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from tempa.rag.ingest import search_memory
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)

_MEET_URL_RE = re.compile(r"https://meet\.google\.com/[a-z0-9\-]+", re.I)
_CALENDAR_HINTS = (
    "calendar",
    "schedule",
    "meeting",
    "meetings",
    "agenda",
    "what's on",
    "whats on",
    "today",
    "tomorrow",
    "next event",
    "meeting name",
    "which meeting",
    "what meeting",
    "event name",
    "standup",
    "stand up",
)
_PC_HINTS = (
    "open vscode",
    "open code",
    "close app",
    "run shell",
    "create file",
    "write file",
    "read file",
)
_GMAIL_HINTS = ("gmail", "inbox", "email", "e-mail")

_WHATSAPP_SYSTEM = """You are Tempa, the owner's personal AI assistant on WhatsApp.
You are warm, direct, and proactive — like a trusted chief of staff texting back.

Rules:
- Answer the user's latest message first. Follow-ups like "what meeting name?" need a direct specific answer.
- Never repeat your previous reply verbatim. If they ask again, give the detail they asked for.
- Lead with the answer or what you did; skip filler ("Sure!", "Great question!").
- Keep replies short (1–4 sentences) unless they ask for detail.
- Use the conversation thread, calendar block, and memory when relevant — cite specifics (event titles, times).
- ONLY say you created, deleted, scheduled, or sent something if "Actions just taken" confirms it.
- NEVER claim you sent an email unless "Actions just taken" says an email was sent.
- NEVER claim you sent a calendar invite unless "Actions just taken" confirms invites were sent.
- If no guests were invited, say the event is only on the owner's calendar.
- If the user asks why an email failed, explain using the last email action result — do not guess.
- NEVER claim a calendar change succeeded if "Actions just taken" says it failed or is empty.
- If calendar data is available, use real event names and times for meeting questions.
- If you lack information, say so honestly instead of guessing.
- Match the user's language when they write in Urdu/Hinglish; stay natural and concise."""


def _is_gmail_task(text: str) -> bool:
    lower = text.lower()
    if any(hint in lower for hint in _GMAIL_HINTS):
        return True
    if "@" in text and any(k in lower for k in ("send", "compose", "write", "email", "mail")):
        return True
    return "mail" in lower and not any(k in lower for k in ("whatsapp", "meet"))


def _is_email_status_followup(text: str) -> bool:
    lower = text.lower().strip().rstrip("?").rstrip(".")
    return lower in {
        "why",
        "reason",
        "what happened",
        "what went wrong",
        "explain",
        "how come",
        "why not",
        "what was the reason",
    }


def _needs_coordinator(text: str) -> bool:
    lower = text.lower()
    if any(hint in lower for hint in _PC_HINTS):
        return True
    return False


def _is_follow_up(text: str) -> bool:
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


def _wants_calendar(text: str) -> bool:
    lower = text.lower()
    if any(hint in lower for hint in _CALENDAR_HINTS):
        return True
    if _is_follow_up(text) and any(k in lower for k in ("meeting", "event", "calendar", "standup")):
        return True
    from tempa.channels.calendar.events import wants_create_event, wants_delete_event

    return wants_create_event(text) or wants_delete_event(text)


def search_chat_memory(query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
    """Memory search tuned for WhatsApp chat — drops noisy semantic/coordinator echoes."""
    try:
        results = search_memory(query, top_k=top_k * 3)
    except Exception as exc:
        logger.warning("Memory search failed: %s", exc)
        return []

    filtered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in results:
        meta = row.get("metadata") or {}
        tags = str(meta.get("tags", ""))
        tool = str(meta.get("tool", ""))
        if "semantic" in tags:
            continue
        if tool == "core" and "reply" in tags:
            continue
        content = row["content"][:350].strip()
        if not content:
            continue
        key = content[:100].lower()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(row)
        if len(filtered) >= top_k:
            break
    return filtered


def _format_memory_block(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "No matching memory yet."
    lines: list[str] = []
    for row in memories:
        meta = row.get("metadata") or {}
        tool = meta.get("tool", "?")
        snippet = row["content"][:350].replace("\n", " ")
        lines.append(f"- [{tool}] {snippet}")
    return "\n".join(lines)



def _format_action_reply(successes: list[str], failures: list[str]) -> str:
    parts: list[str] = []
    if successes:
        parts.append("\n".join(successes))
    if failures:
        parts.append("\n".join(failures))
    return "\n\n".join(parts) if parts else ""


def _run_actions(user_message: str, context: dict[str, Any]) -> tuple[list[str], list[str]]:
    successes: list[str] = []
    failures: list[str] = []
    from tempa.channels.calendar.events import (
        _attendee_names_from_text,
        try_create_event_from_message,
        try_delete_event_from_message,
        try_invite_guests_from_message,
    )
    from tempa.channels.whatsapp.action_state import record_action
    from tempa.channels.whatsapp.conversation import get_recent_messages

    recent_texts = [m.get("text", "") for m in get_recent_messages(8)]

    delete_result = try_delete_event_from_message(user_message, recent_texts=recent_texts)
    if delete_result.error != "not a delete request":
        if delete_result.ok and delete_result.deleted:
            names = ", ".join(f"'{name}'" for name in delete_result.deleted)
            successes.append(f"Deleted from calendar: {names}.")
            record_action("calendar", {"status": "deleted", "summary": delete_result.deleted[0]})
        else:
            failures.append(f"Could not delete calendar event: {delete_result.error}")
            record_action("calendar", {"status": "error", "error": delete_result.error})

    create_result = try_create_event_from_message(user_message, recent_texts=recent_texts)
    created_with_invites = False
    if create_result.error != "not a create request":
        if create_result.ok:
            line = f"Created calendar event '{create_result.summary}' at {create_result.when}."
            invited = create_result.invited_attendees or []
            if invited:
                line += f" Calendar invite sent to {', '.join(invited)}."
                created_with_invites = True
            else:
                guest_names = _attendee_names_from_text(user_message)
                if not guest_names:
                    for msg in recent_texts:
                        guest_names.extend(_attendee_names_from_text(msg))
                if guest_names:
                    failures.append(
                        f"Could not send calendar invite: No guest email found for {guest_names[0]}. "
                        f"What's {guest_names[0]}'s email?"
                    )
            if create_result.meet_url:
                line += f" Meet link: {create_result.meet_url}"
                from tempa.channels.calendar.events import schedule_meet_join_for_event

                try:
                    job_id = schedule_meet_join_for_event(
                        create_result.meet_url,
                        summary=create_result.summary,
                        start=create_result.start_at,
                    )
                    if job_id:
                        line += f" Tempa is joining the Meet now (job {job_id[:8]}…)."
                        record_action(
                            "meet",
                            {
                                "status": "queued",
                                "meeting_id": job_id,
                                "meet_url": create_result.meet_url,
                            },
                        )
                except RuntimeError as exc:
                    failures.append(f"Could not auto-join Meet: {exc}")
            successes.append(line)
            record_action(
                "calendar",
                {
                    "status": "created",
                    "summary": create_result.summary,
                    "when": create_result.when,
                    "meet_url": create_result.meet_url,
                    "attendees": invited,
                },
            )
        else:
            failures.append(f"Could not create calendar event: {create_result.error}")
            record_action("calendar", {"status": "error", "error": create_result.error})

    invite_result = try_invite_guests_from_message(user_message, recent_texts=recent_texts)
    if invite_result.error != "not an invite request":
        if invite_result.ok:
            guests = ", ".join(invite_result.attendees or [])
            successes.append(
                f"Sent calendar invite for '{invite_result.summary}' to {guests}."
            )
            record_action(
                "calendar",
                {
                    "status": "invited",
                    "summary": invite_result.summary,
                    "attendees": invite_result.attendees,
                },
            )
        elif not (create_result.ok and created_with_invites):
            failures.append(f"Could not send calendar invite: {invite_result.error}")
            record_action("calendar", {"status": "error", "error": invite_result.error})

    meet_url = context.get("meet_url") or _MEET_URL_RE.search(user_message)
    if meet_url:
        url = meet_url if isinstance(meet_url, str) else meet_url.group(0)
        from tempa.meet.service import schedule_meeting_join

        try:
            meeting_id = schedule_meeting_join(url, title=user_message[:80] or "WhatsApp Meet")
            record_action(
                "meet",
                {"status": "queued", "meeting_id": meeting_id, "meet_url": url},
            )
            successes.append(f"Joining Google Meet now (job {meeting_id}).")
        except Exception as exc:
            record_action("meet", {"status": "failed", "meet_url": url, "error": str(exc)})
            failures.append(f"Could not join Meet: {exc}")
    return successes, failures


def _fetch_memory_answer(user_message: str) -> str:
    try:
        from tempa.rag.agent import run_rag_agent

        return run_rag_agent(user_message, mode="fast")
    except Exception as exc:
        logger.warning("Fast RAG failed, falling back to chat memory: %s", exc)
        memories = search_chat_memory(user_message, top_k=5)
        return _format_memory_block(memories)


def _run_whatsapp_reply_sync(user_message: str, context: dict[str, Any]) -> str:
    router = get_router()

    from tempa.channels.whatsapp.conversation import get_recent_messages

    recent = get_recent_messages(12)

    include_calendar = _wants_calendar(user_message) or (
        _is_follow_up(user_message) and any("meeting" in m.get("text", "").lower() for m in recent[-4:])
    )
    action_successes, action_failures = _run_actions(user_message, context)
    action_notes = action_successes + action_failures
    memory_answer = _fetch_memory_answer(user_message)

    from tempa.channels.calendar.events import (
        wants_add_guest,
        wants_create_event,
        wants_delete_event,
        wants_send_calendar_invite,
    )

    if (action_successes or action_failures) and (
        wants_create_event(user_message)
        or wants_delete_event(user_message)
        or wants_send_calendar_invite(user_message)
        or wants_add_guest(user_message)
    ):
        return _format_action_reply(action_successes, action_failures)

    from tempa.agents.grounding import build_grounding_pack, format_grounding_for_prompt
    from tempa.router.verifier import verify_reply

    pack = build_grounding_pack(
        user_message,
        context,
        action_notes=action_notes,
        memory_answer=memory_answer,
        include_calendar=include_calendar,
    )
    user_prompt = format_grounding_for_prompt(
        pack,
        owner=context.get("whatsapp_number", "owner"),
    )

    try:
        response = router.chat_completion(
            category="text",
            messages=[
                {"role": "system", "content": _WHATSAPP_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=400,
            temperature=0.2,
        )
        content = (response.choices[0].message.content or "").strip()
        if content:
            ok, verified = verify_reply(content, pack)
            return verified if not ok else content
    except Exception as exc:
        logger.exception("WhatsApp fast reply failed: %s", exc)

    if action_notes:
        return _format_action_reply(action_successes, action_failures)
    return "I'm here — I had trouble generating a reply. Please try again in a moment."


async def _run_gmail_whatsapp_reply(user_message: str, context: dict[str, Any]) -> str:
    from tempa.agents.specialists import _whatsapp_gmail_reply, run_gmail_agent
    from tempa.channels.whatsapp.conversation import get_recent_messages

    enriched = dict(context)
    enriched["inbound_whatsapp"] = True
    enriched["skip_ingest"] = True
    enriched["user_message"] = user_message
    enriched["recent_user_messages"] = [
        m.get("text", "") for m in get_recent_messages(8) if m.get("role") == "user"
    ]
    try:
        result = await run_gmail_agent(user_message, enriched)
        short = _whatsapp_gmail_reply(result)
        return short or result
    except Exception as exc:
        logger.exception("Gmail WhatsApp reply failed")
        return f"Couldn't fetch your inbox right now: {exc}"


async def run_whatsapp_reply(user_message: str, context: dict[str, Any] | None = None) -> str:
    """Fast Groq reply with memory + calendar; coordinator for PC tasks; direct path for Gmail."""
    from tempa.channels.whatsapp.action_state import explain_last_action
    from tempa.channels.whatsapp.intent import WhatsAppIntent, route_whatsapp_intent

    context = context or {}
    intent = route_whatsapp_intent(user_message, context)

    if intent == WhatsAppIntent.ACTION_STATUS_FOLLOWUP:
        explanation = explain_last_action()
        if explanation:
            return explanation

    if intent == WhatsAppIntent.GMAIL:
        return await _run_gmail_whatsapp_reply(user_message, context)

    if intent == WhatsAppIntent.COORDINATOR:
        from tempa.agents.graph import run_coordinator

        merged_context = {
            **context,
            "channel": "whatsapp",
            "inbound_whatsapp": True,
        }
        return await run_coordinator(user_message, merged_context)

    if intent in (WhatsAppIntent.CHAT, WhatsAppIntent.CALENDAR):
        return await asyncio.to_thread(_run_whatsapp_reply_sync, user_message, context)

    return await asyncio.to_thread(_run_whatsapp_reply_sync, user_message, context)
