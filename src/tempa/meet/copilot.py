"""Live meeting copilot: detect questions and suggest Meet chat replies."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tempa.core.events import event_bus
from tempa.meet.session_registry import get_session
from tempa.router.groq_router import get_router
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

QUESTION_PATTERNS = [
    re.compile(r"\?\s*$"),
    re.compile(r"\b(what do you think|your thoughts|can you|could you|do you agree)\b", re.I),
    re.compile(r"\b(any updates|status on|thoughts on)\b", re.I),
]


def _read_transcript_tail(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if row.get("type") == "segment" and row.get("text"):
            speaker = row.get("speaker") or "Unknown"
            lines.append(f"{speaker}: {row['text']}")
    return "\n".join(lines)[-max_chars:]


def _read_notes(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")[-4000:]
    return ""


def _looks_like_question(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    return any(p.search(t) for p in QUESTION_PATTERNS)


async def _generate_suggestions(
    transcript: str,
    notes: str,
    *,
    title: str,
    trigger_context: str,
) -> list[dict[str, str]]:
    if not transcript.strip() and not trigger_context:
        return []
    router = get_router()
    prompt = (
        f"You are a meeting copilot for '{title}'. Suggest 1-3 concise replies the user could "
        f"send in Google Meet chat. Ground answers in the transcript and notes. "
        f"Return JSON array of objects with keys: text, rationale.\n\n"
        f"Trigger: {trigger_context}\n\nNotes:\n{notes}\n\nTranscript:\n{transcript[-8000:]}"
    )
    try:
        response = router.chat_completion(
            category="reasoning",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
        content = (response.choices[0].message.content or "").strip()
        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end > start:
            items = json.loads(content[start : end + 1])
            if isinstance(items, list):
                out: list[dict[str, str]] = []
                for item in items[:3]:
                    if isinstance(item, dict) and item.get("text"):
                        out.append(
                            {
                                "text": str(item["text"]),
                                "rationale": str(item.get("rationale") or ""),
                            }
                        )
                return out
    except Exception:
        logger.exception("Copilot suggestion generation failed")
    return []


async def copilot_loop(
    meeting_id: str,
    transcript_path: Path,
    notes_path: Path,
    suggestions_path: Path,
    stop_event: asyncio.Event,
    *,
    title: str = "",
    interval_s: int = 25,
) -> None:
    suggestions_path.parent.mkdir(parents=True, exist_ok=True)
    last_transcript_len = 0
    seen_triggers: set[str] = set()

    while not stop_event.is_set():
        await asyncio.sleep(interval_s)
        transcript = _read_transcript_tail(transcript_path)
        if len(transcript) <= last_transcript_len + 30:
            continue

        new_tail = transcript[last_transcript_len:]
        last_transcript_len = len(transcript)

        trigger_lines = [ln for ln in new_tail.splitlines() if _looks_like_question(ln)]
        if not trigger_lines:
            continue

        trigger_context = trigger_lines[-1]
        trigger_key = trigger_context[:120]
        if trigger_key in seen_triggers:
            continue
        seen_triggers.add(trigger_key)

        notes = _read_notes(notes_path)
        suggestions = await _generate_suggestions(
            transcript,
            notes,
            title=title or meeting_id,
            trigger_context=trigger_context,
        )
        if not suggestions:
            continue

        for sug in suggestions:
            row = {
                "id": str(uuid.uuid4()),
                "meeting_id": meeting_id,
                "text": sug["text"],
                "rationale": sug.get("rationale", ""),
                "trigger": trigger_context,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            with suggestions_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            await event_bus.publish_json("meet", "copilot_suggestion", row)

            settings = get_settings()
            if settings.meet_copilot_whatsapp_notify:
                try:
                    from tempa.channels.whatsapp.outbound import send_whatsapp_message
                    from tempa.channels.whatsapp.reply import load_default_whatsapp_number

                    number = load_default_whatsapp_number()
                    if number:
                        msg = f"*Suggested reply* ({title}):\n{sug['text']}"
                        await send_whatsapp_message(number, msg[:3500], source_channel="whatsapp_auto_reply")
                except Exception:
                    logger.debug("Copilot WhatsApp notify failed", exc_info=True)


async def send_meeting_chat(meeting_id: str, text: str) -> bool:
    from tempa.meet.chat import send_chat_message

    session = get_session(meeting_id)
    if session is None:
        return False
    settings = get_settings()
    prefix = (settings.meet_chat_prefix or "").strip()
    message = f"{prefix} {text}".strip() if prefix else text
    return await send_chat_message(session.page, message)
