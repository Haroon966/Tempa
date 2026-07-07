from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from tempa.channels.whatsapp.chat import run_whatsapp_reply
from tempa.channels.whatsapp.media import transcribe_whatsapp_audio
from tempa.channels.whatsapp.numbers import is_owner_whatsapp_number, remember_message_lid_mapping
from tempa.channels.whatsapp.outbound import send_whatsapp_message
from tempa.channels.whatsapp.session import is_auto_reply_paused, needs_qr_rescan
from tempa.core.events import event_bus
from tempa.rag.ingest import ingest_text
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_MEET_URL_RE = re.compile(r"https://meet\.google\.com/[a-z0-9\-]+", re.I)


def _default_reply_number_path() -> Path:
    return get_settings().sessions_dir / "whatsapp" / "default_number.txt"


def save_default_whatsapp_number(number: str) -> None:
    from tempa.channels.whatsapp.numbers import get_owner_whatsapp_number

    path = _default_reply_number_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(get_owner_whatsapp_number() or number.strip(), encoding="utf-8")


def load_default_whatsapp_number() -> str:
    from tempa.channels.whatsapp.numbers import get_owner_whatsapp_number

    return get_owner_whatsapp_number()


def _ingest_inbound(
    text: str,
    *,
    participant: str,
    participants: list[str],
    is_group: bool,
) -> None:
    try:
        ingest_text(
            text,
            tool="whatsapp",
            source=participant,
            participants=participants,
            tags=["inbound", "group"] if is_group else ["inbound"],
        )
    except Exception:
        logger.exception("Failed to index WhatsApp message")


async def _resolve_message_text(text: str, raw_item: dict) -> str:
    if text != "[voice note]":
        return text
    from tempa.channels.whatsapp.schemas import _has_audio

    if not _has_audio(raw_item.get("message", {}) if isinstance(raw_item.get("message"), dict) else {}):
        return text
    transcript = await transcribe_whatsapp_audio(raw_item)
    return transcript or text


async def handle_forwarded_voice_note(raw_item: dict, message_id: str = "") -> dict:
    """Transcribe a voice note forwarded to the linked account self-chat; summarize to owner."""
    from tempa.channels.whatsapp.conversation import has_assistant_reply_for, record_conversation_turn
    from tempa.channels.whatsapp.numbers import get_owner_whatsapp_number
    from tempa.router.groq_router import get_router

    if message_id and has_assistant_reply_for(message_id):
        return {"skipped": "duplicate"}

    transcript = await transcribe_whatsapp_audio(raw_item)
    if not transcript.strip():
        return {"error": "empty_transcript"}

    resp = get_router().chat_completion(
        category="text",
        messages=[
            {
                "role": "system",
                "content": "Summarize this forwarded WhatsApp voice message in 3-6 clear bullet points.",
            },
            {"role": "user", "content": transcript},
        ],
    )
    summary = resp.choices[0].message.content or ""
    owner = get_owner_whatsapp_number() or load_default_whatsapp_number()
    from tempa.channels.whatsapp.numbers import get_owner_delivery_jid

    delivery = get_owner_delivery_jid() or owner
    body = f"*Forwarded voice message*\n\n{summary.strip()}\n\n_Transcript:_\n{transcript.strip()}"
    result = await send_whatsapp_message(
        delivery,
        body,
        skip_safety=True,
        require_user_confirmation=False,
        source_channel="coordinator",
    )
    record_conversation_turn(
        role="assistant",
        text=body,
        from_number=owner,
        message_id=message_id,
        chat_id=delivery,
    )
    return {"sent": True, "result": result}


async def handle_inbound_whatsapp(
    from_number: str,
    text: str,
    message_id: str,
    *,
    chat_id: str = "",
    is_group: bool = False,
    raw_item: dict | None = None,
) -> dict:
    """Index every message; auto-reply only to the configured owner number."""
    if not from_number or not text.strip():
        return {"handled": 0}

    if is_auto_reply_paused():
        from tempa.channels.whatsapp.session import sync_connection_from_bridge

        await sync_connection_from_bridge()
    if is_auto_reply_paused():
        await event_bus.publish_json("channel", "whatsapp_paused", "disconnected")
        return {"handled": 0, "paused": True, "needs_qr_rescan": needs_qr_rescan()}

    raw_item = raw_item or {}
    remember_message_lid_mapping(raw_item)

    from tempa.channels.whatsapp.conversation import has_assistant_reply_for, record_conversation_turn

    if message_id and has_assistant_reply_for(message_id):
        return {"handled": 0, "duplicate": True, "message_id": message_id}

    text = await _resolve_message_text(text, raw_item)

    record_conversation_turn(
        role="user",
        text=text,
        from_number=from_number,
        message_id=message_id,
        chat_id=chat_id,
        raw_item=raw_item,
    )

    participant = chat_id if is_group else from_number
    participants = [participant, from_number] if is_group else [from_number]

    if not is_owner_whatsapp_number(from_number, chat_id=chat_id, raw_item=raw_item):
        # #region agent log
        from tempa.debug_agent_log import agent_log

        agent_log(
            location="reply.py:handle_inbound_whatsapp:skip",
            message="skipped auto-reply — sender not owner",
            data={
                "from_number": from_number,
                "chat_id": chat_id,
                "owner": load_default_whatsapp_number(),
            },
            hypothesis_id="H6",
        )
        # #endregion
        asyncio.create_task(
            asyncio.to_thread(
                _ingest_inbound,
                text,
                participant=participant,
                participants=participants,
                is_group=is_group,
            )
        )
        logger.debug("Ingested WhatsApp from %s (no auto-reply)", from_number)
        return {"handled": 0, "ingested": True, "skipped_reply": True, "from": from_number}

    meet_url = _MEET_URL_RE.search(text)
    meet_url = meet_url.group(0) if meet_url else None

    try:
        reply = await run_whatsapp_reply(
            text,
            context={
                "channel": "whatsapp",
                "whatsapp_number": from_number,
                "whatsapp_chat_id": chat_id or from_number,
                "is_group": is_group,
                "message_id": message_id,
                "inbound_whatsapp": True,
                "meet_url": meet_url,
            },
        )
    except Exception as exc:
        logger.exception("WhatsApp reply failed")
        reply = f"Tempa encountered an error: {exc}"

    reply_target = chat_id if chat_id and "@" in chat_id else from_number
    from tempa.channels.whatsapp.numbers import owner_delivery_for_number

    if is_owner_whatsapp_number(from_number, chat_id=chat_id, raw_item=raw_item):
        reply_target = owner_delivery_for_number(from_number)
    send_result = await send_whatsapp_message(reply_target, reply, source_channel="whatsapp_auto_reply")

    record_conversation_turn(
        role="assistant",
        text=reply,
        from_number=from_number,
        chat_id=chat_id or from_number,
    )

    return {"handled": 1, "reply": reply, "send": send_result, "meet_url": meet_url}
