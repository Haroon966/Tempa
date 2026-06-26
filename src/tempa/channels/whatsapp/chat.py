from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
from typing import Any

from tempa.rag.ingest import search_memory
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)

_whatsapp_reply_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="whatsapp-reply",
)

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
_TRIVIAL_CHAT_RE = re.compile(
    r"^(hi|hello|hey|salam|aoa|assalam|ok|thanks|thank you|yo|hiya)[\s!.?]*$",
    re.I,
)

_WHATSAPP_SYSTEM = """You are Tempa, the owner's personal AI assistant on WhatsApp.
You are warm, direct, and proactive — like a trusted chief of staff texting back.

Rules:
- Answer the user's latest message first. Follow-ups like "what meeting name?" need a direct specific answer.
- Never repeat your previous reply verbatim. If they ask again, give the detail they asked for.
- Lead with the answer or what you did; skip filler ("Sure!", "Great question!").
- Keep replies short (1–4 sentences) unless they ask for detail.
- Use the conversation thread, calendar block, inbox block, and memory when relevant — cite specifics (event titles, times, email subjects).
- Distinguish canceled vs active calendar events; only reference meeting minutes when archive data confirms them.
- Use conversation thread for follow-ups; do not ask the user to repeat what was just discussed.
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


def _is_trivial_chat(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _TRIVIAL_CHAT_RE.match(stripped):
        return True
    lower = stripped.lower()
    if len(stripped) <= 40 and lower.startswith(("hi ", "hello ", "hey ", "hi,", "hello,", "hey,")):
        return True
    return False


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
    from tempa.channels.calendar.events import apply_calendar_actions_from_message
    from tempa.channels.whatsapp.action_state import record_action
    from tempa.channels.whatsapp.conversation import get_recent_messages

    recent_texts = [m.get("text", "") for m in get_recent_messages(8)]
    cal = apply_calendar_actions_from_message(user_message, recent_texts=recent_texts)
    successes = list(cal.get("successes") or [])
    failures = list(cal.get("failures") or [])

    action = cal.get("action", "none")
    if action == "deleted":
        if cal.get("ok"):
            record_action("calendar", {"status": "deleted", "summary": (cal.get("deleted") or ["event"])[0]})
        else:
            record_action("calendar", {"status": "error", "error": cal.get("error", "")})
    elif action == "created":
        if cal.get("ok"):
            record_action(
                "calendar",
                {
                    "status": "created",
                    "summary": cal.get("summary", ""),
                    "when": cal.get("when", ""),
                    "meet_url": cal.get("meet_url"),
                    "attendees": cal.get("invited_attendees") or [],
                },
            )
            if cal.get("meet_job_id") and cal.get("meet_url"):
                record_action(
                    "meet",
                    {
                        "status": "queued",
                        "meeting_id": cal["meet_job_id"],
                        "meet_url": cal["meet_url"],
                    },
                )
        else:
            record_action("calendar", {"status": "error", "error": cal.get("error", "")})
    elif action == "invited":
        if cal.get("ok"):
            record_action(
                "calendar",
                {
                    "status": "invited",
                    "summary": cal.get("summary", ""),
                    "attendees": cal.get("invited_attendees") or [],
                },
            )
        elif cal.get("error"):
            record_action("calendar", {"status": "error", "error": cal.get("error", "")})

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


def _fetch_memory_answer(user_message: str, *, timeout_s: float = 4.0) -> str:
    """Lightweight memory lookup for WhatsApp — never block on full RAG graph."""
    if _is_trivial_chat(user_message):
        return "No matching memory yet."

    def _search() -> str:
        memories = search_chat_memory(user_message, top_k=3)
        return _format_memory_block(memories)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_search).result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        logger.warning("WhatsApp memory search timed out after %.1fs", timeout_s)
        return "No matching memory yet."
    except Exception as exc:
        logger.warning("WhatsApp memory search failed: %s", exc)
        return "No matching memory yet."


def _sync_before_read_sync(user_message: str, *, include_calendar: bool = False) -> None:
    from tempa.agents.intent import wants_calendar_full, wants_gmail_full

    if wants_gmail_full(user_message):
        try:
            from tempa.channels.gmail.snapshot import refresh_gmail_snapshot

            refresh_gmail_snapshot()
        except Exception as exc:
            logger.warning("Gmail sync-before-read failed: %s", exc)

    if wants_calendar_full(user_message, include_calendar=include_calendar):
        try:
            from tempa.channels.calendar.sync import sync_calendar_snapshot

            sync_calendar_snapshot()
        except Exception as exc:
            logger.warning("Calendar sync-before-read failed: %s", exc)


def _run_whatsapp_reply_sync(user_message: str, context: dict[str, Any]) -> str:
    router = get_router()

    include_calendar = _wants_calendar(user_message)
    _sync_before_read_sync(user_message, include_calendar=include_calendar)
    action_successes, action_failures = _run_actions(user_message, context)
    action_notes = action_successes + action_failures
    memory_answer = _fetch_memory_answer(user_message)
    if memory_answer == "No matching memory yet.":
        memory_answer = "Memory search unavailable."

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
        from tempa.agents.grounding import build_grounding_pack
        from tempa.router.verifier import verify_reply

        action_reply = _format_action_reply(action_successes, action_failures)
        pack = build_grounding_pack(
            user_message,
            context,
            action_notes=action_notes,
            memory_answer=memory_answer,
            include_calendar=include_calendar,
        )
        ok, verified = verify_reply(action_reply, pack)
        return verified if not ok else action_reply

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


async def _try_live_meeting_command(user_message: str) -> str | None:
    """Handle mid-meeting WhatsApp commands against the active Meet session."""
    from tempa.meet.archive import read_live_meeting_state
    from tempa.meet.copilot import send_meeting_chat
    from tempa.meet.service import get_active_meeting_ids

    active = get_active_meeting_ids()
    if not active:
        return None

    lower = user_message.lower().strip()
    meeting_id = active[0]

    if any(
        phrase in lower
        for phrase in (
            "what's happening in my meeting",
            "whats happening in my meeting",
            "what is happening in my meeting",
            "my meeting now",
            "live meeting",
            "in my meeting",
        )
    ):
        state = read_live_meeting_state(meeting_id)
        notes = (state.get("live_notes") or "").strip()
        tail = (state.get("transcript_tail") or "").strip()
        body = notes or tail or "No live notes yet — still listening."
        return f"*Live meeting:*\n{body[:2500]}"

    tell_prefixes = ("tell them ", "say to them ", "message them ", "send to meet ")
    for prefix in tell_prefixes:
        if lower.startswith(prefix):
            text = user_message[len(prefix) :].strip()
            if not text:
                return "What should I say in the Meet chat?"
            ok = await send_meeting_chat(meeting_id, text)
            if ok:
                return f"Sent to Meet chat: {text[:500]}"
            return "Couldn't send — no active Meet session or chat panel unavailable."
    return None


async def run_whatsapp_reply(user_message: str, context: dict[str, Any] | None = None) -> str:
    """Fast Groq reply with memory + calendar; coordinator for PC tasks; direct path for Gmail."""
    from tempa.channels.whatsapp.action_state import explain_last_action
    from tempa.channels.whatsapp.intent import WhatsAppIntent, route_whatsapp_intent

    context = context or {}

    async def _generate() -> str:
        live = await _try_live_meeting_command(user_message)
        if live:
            return live

        intent = route_whatsapp_intent(user_message, context)

        if intent == WhatsAppIntent.ACTION_STATUS_FOLLOWUP:
            explanation = explain_last_action()
            if explanation:
                return explanation

        if intent == WhatsAppIntent.GMAIL:
            return await _run_gmail_whatsapp_reply(user_message, context)

        if intent == WhatsAppIntent.COORDINATOR:
            from tempa.agents.graph import run_coordinator_full

            merged_context = {
                **context,
                "channel": "whatsapp",
                "inbound_whatsapp": True,
            }
            result = await run_coordinator_full(user_message, merged_context)
            return str(result.get("response") or "")

        from tempa.settings import get_settings

        mode = (get_settings().tempa_coordinator or "langgraph").strip().lower()
        if mode == "varys" and intent == WhatsAppIntent.CHAT and not _is_trivial_chat(user_message):
            from tempa.agents.graph import run_coordinator_full

            merged_context = {
                **context,
                "channel": "whatsapp",
                "inbound_whatsapp": True,
            }
            result = await run_coordinator_full(user_message, merged_context)
            return str(result.get("response") or "")

        if intent in (WhatsAppIntent.CHAT, WhatsAppIntent.CALENDAR):
            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(_whatsapp_reply_pool, _run_whatsapp_reply_sync, user_message, context),
                timeout=40.0,
            )

        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(_whatsapp_reply_pool, _run_whatsapp_reply_sync, user_message, context),
            timeout=40.0,
        )

    try:
        return await asyncio.wait_for(_generate(), timeout=40.0)
    except asyncio.TimeoutError:
        logger.warning("WhatsApp reply generation timed out")
        return "I'm here — that took too long. Please try again."
