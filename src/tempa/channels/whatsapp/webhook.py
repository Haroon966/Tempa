from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from tempa.channels.whatsapp.conversation import record_conversation_turn
from tempa.channels.whatsapp.inbound_queue import enqueue_inbound, start_inbound_worker
from tempa.channels.whatsapp.schemas import EvolutionWebhookPayload, WhatsAppMessage, parse_messages_upsert
from tempa.channels.whatsapp.client import EvolutionWhatsAppClient
from tempa.channels.whatsapp.session import store_qr_code, update_connection_state
from tempa.core.events import event_bus
from tempa.debug_agent_log import agent_log

_seen_message_ids: set[str] = set()
_seen_message_order: deque[str] = deque(maxlen=500)


async def _enable_webhook_after_connect() -> None:
    from tempa.settings import get_settings

    settings = get_settings()
    base = settings.tempa_webhook_base_url.strip() or (
        f"http://127.0.0.1:{settings.tempa_daemon_port}"
    )
    webhook_url = f"{base.rstrip('/')}/webhooks/whatsapp"
    try:
        await EvolutionWhatsAppClient().set_webhook(webhook_url)
    except Exception:
        pass


def get_recent_messages(limit: int = 20) -> list[dict[str, Any]]:
    from tempa.channels.whatsapp.conversation import get_recent_messages as _get

    return _get(limit)


def _dedupe_key(msg: WhatsAppMessage) -> str:
    if msg.message_id:
        return msg.message_id
    return f"{msg.from_number}:{msg.chat_id}:{msg.text}:{msg.timestamp or ''}"


def _mark_seen(key: str) -> bool:
    if key in _seen_message_ids:
        return False
    _seen_message_ids.add(key)
    _seen_message_order.append(key)
    while len(_seen_message_order) > 500:
        old = _seen_message_order.popleft()
        _seen_message_ids.discard(old)
    return True


async def handle_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    # #region agent log
    agent_log(
        location="webhook.py:handle_webhook:entry",
        message="webhook received",
        data={"event": payload.get("event"), "has_data": bool(payload.get("data"))},
        hypothesis_id="H2",
    )
    # #endregion
    if not payload or not payload.get("event"):
        return {"ignored": "empty_or_invalid"}
    try:
        model = EvolutionWebhookPayload.model_validate(payload)
    except Exception:
        event_raw = str(payload.get("event") or "")
        if not event_raw:
            return {"ignored": "invalid_payload"}
        model = EvolutionWebhookPayload(
            event=event_raw,
            instance=payload.get("instance"),
            data=payload.get("data") if isinstance(payload.get("data"), dict) else payload,
        )
    event = model.event.upper().replace(".", "_")

    if event in {"MESSAGES_UPSERT", "MESSAGES.UPSERT"}:
        messages = parse_messages_upsert(payload)
        queued = 0
        for msg in messages:
            key = _dedupe_key(msg)
            if not _mark_seen(key):
                continue
            if await enqueue_inbound(msg):
                queued += 1
        # #region agent log
        agent_log(
            location="webhook.py:messages_upsert",
            message="messages queued",
            data={"parsed": len(messages), "queued": queued},
            hypothesis_id="H5",
        )
        # #endregion
        return {"handled": 0, "queued": queued}

    if event in {"CONNECTION_UPDATE", "CONNECTION.UPDATE"}:
        state = model.data.get("state", "unknown")
        snapshot = await asyncio.to_thread(update_connection_state, str(state))
        # #region agent log
        agent_log(
            location="webhook.py:connection_update",
            message="connection state updated",
            data={"state": state, "connected": snapshot.get("connected")},
            hypothesis_id="H1",
        )
        # #endregion
        if str(state).lower() in {"open", "connected"}:
            from tempa.channels.whatsapp.session import clear_qr_code

            await asyncio.to_thread(clear_qr_code)
            asyncio.create_task(_enable_webhook_after_connect())
        await event_bus.publish_json("channel", "whatsapp_connection", state)
        if snapshot.get("needs_qr_rescan"):
            await event_bus.publish_json("channel", "whatsapp_qr_required", "Scan QR to reconnect")
        return {"state": state, **snapshot}

    if event in {"QRCODE_UPDATED", "QRCODE.UPDATED"}:
        qrcode = model.data.get("qrcode") or model.data

        async def _store_qr() -> None:
            if not isinstance(qrcode, dict):
                return
            base64_qr = qrcode.get("base64")
            if not (isinstance(base64_qr, str) and base64_qr):
                code = qrcode.get("code")
                if isinstance(code, str) and code:
                    base64_qr = await asyncio.to_thread(
                        EvolutionWhatsAppClient._qr_image_from_code, code
                    )
            if isinstance(base64_qr, str) and base64_qr:
                if not base64_qr.startswith("data:"):
                    base64_qr = f"data:image/png;base64,{base64_qr}"
                await asyncio.to_thread(store_qr_code, base64_qr)
                # #region agent log
                agent_log(
                    location="webhook.py:qrcode_updated",
                    message="qr stored from webhook",
                    data={"qr_len": len(base64_qr)},
                    hypothesis_id="H8",
                    run_id="post-fix",
                )
                # #endregion

        await _store_qr()
        await event_bus.publish_json("channel", "whatsapp_qr", "updated")
        return {"qr": "updated"}

    return {"ignored": event}


async def ensure_webhook_worker() -> None:
    await start_inbound_worker()
