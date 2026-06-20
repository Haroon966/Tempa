from __future__ import annotations

import asyncio
import logging

from tempa.channels.whatsapp.client import EvolutionWhatsAppClient
from tempa.channels.whatsapp.conversation import record_conversation_turn
from tempa.channels.whatsapp.session import is_auto_reply_paused
from tempa.core.events import event_bus
from tempa.rag.ingest import ingest_text
from tempa.router.safety import screen_outbound_message

logger = logging.getLogger(__name__)


def _auto_reply_skip_confirm() -> bool:
    try:
        import yaml

        from tempa.settings import get_settings

        path = get_settings().config_dir / "permissions.yaml"
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return bool(data.get("whatsapp_auto_reply_skip_confirm", True))
    except Exception:
        return True


async def send_whatsapp_message(
    number: str,
    text: str,
    *,
    skip_safety: bool = False,
    require_user_confirmation: bool | None = None,
    source_channel: str = "coordinator",
) -> dict:
    from tempa.channels.whatsapp.session import sync_connection_from_evolution

    if require_user_confirmation is None:
        require_user_confirmation = source_channel not in ("whatsapp_auto_reply", "whatsapp")

    if require_user_confirmation and not skip_safety:
        from tempa.core.notifications import notify
        from tempa.core.pending_actions import create_pending_action

        action = create_pending_action(
            "whatsapp_send",
            {"number": number, "text": text},
            source_channel=source_channel,
            risk_level="high",
            title=f"WhatsApp to {number}",
        )
        await notify(
            "pending_action",
            title="WhatsApp message needs approval",
            body=text[:120],
            pending_action_id=action["id"],
        )
        return {
            "status": "pending",
            "pending_action_id": action["id"],
            "reason": "Awaiting user confirmation",
        }

    if is_auto_reply_paused():
        await sync_connection_from_evolution()
    if is_auto_reply_paused():
        return {"status": "paused", "reason": "WhatsApp disconnected — scan QR to reconnect"}
    if skip_safety:
        allowed, reason = True, "skipped"
    else:
        allowed, reason = await asyncio.to_thread(screen_outbound_message, text)
    if not allowed:
        await event_bus.publish_json("channel", "blocked", reason[:120])
        return {"status": "blocked", "reason": reason}
    client = EvolutionWhatsAppClient()
    result = await client.send_text(number, text)
    record_conversation_turn(role="assistant", text=text, from_number=number)
    asyncio.create_task(
        asyncio.to_thread(
            ingest_text,
            text,
            tool="whatsapp",
            source=number,
            participants=[number],
            tags=["outbound"],
        )
    )
    await event_bus.publish_json("channel", "sent", number)
    return {"status": "sent", "result": result}


async def send_whatsapp_media(
    number: str,
    file_path: str,
    *,
    caption: str = "",
    mediatype: str = "document",
    require_user_confirmation: bool = True,
) -> dict:
    if require_user_confirmation:
        from tempa.core.notifications import notify
        from tempa.core.pending_actions import create_pending_action

        action = create_pending_action(
            "whatsapp_send",
            {"number": number, "text": caption, "media_path": file_path, "mediatype": mediatype},
            source_channel="coordinator",
            risk_level="high",
            title=f"WhatsApp media to {number}",
        )
        await notify(
            "pending_action",
            title="WhatsApp media needs approval",
            body=caption or file_path,
            pending_action_id=action["id"],
        )
        return {"status": "pending", "pending_action_id": action["id"]}

    client = EvolutionWhatsAppClient()
    return await client.send_media(number, file_path, caption=caption, mediatype=mediatype)
