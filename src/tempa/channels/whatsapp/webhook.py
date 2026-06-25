from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from tempa.channels.whatsapp.conversation import record_conversation_turn
from tempa.channels.whatsapp.dedupe import bootstrap as bootstrap_dedupe, is_seen, mark_seen as persist_mark_seen
from tempa.channels.whatsapp.inbound_queue import enqueue_inbound, start_inbound_worker
from tempa.channels.whatsapp.schemas import (
    EvolutionWebhookPayload,
    WhatsAppMessage,
    parse_messages_upsert,
    parse_outbound_messages_upsert,
)
from tempa.channels.whatsapp.client import WhatsAppBridgeClient
from tempa.channels.whatsapp.session import store_qr_code, update_connection_state
from tempa.core.events import event_bus
from tempa.debug_agent_log import agent_log

import logging

logger = logging.getLogger(__name__)

_seen_message_ids: set[str] = set()
_seen_message_order: deque[str] = deque(maxlen=500)
_MAX_MESSAGE_AGE_SECONDS = 3600


async def _enable_webhook_after_connect() -> None:
    from tempa.settings import get_settings

    settings = get_settings()
    base = settings.tempa_webhook_base_url.strip() or (
        f"http://127.0.0.1:{settings.tempa_daemon_port}"
    )
    webhook_url = f"{base.rstrip('/')}/webhooks/whatsapp"
    try:
        await WhatsAppBridgeClient().set_webhook(webhook_url)
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
    if is_seen(key):
        return False
    if key in _seen_message_ids:
        return False
    if not persist_mark_seen(key):
        return False
    _seen_message_ids.add(key)
    _seen_message_order.append(key)
    while len(_seen_message_order) > 500:
        old = _seen_message_order.popleft()
        _seen_message_ids.discard(old)
    return True


_seen_bootstrapped = False


def _bootstrap_seen_from_history() -> None:
    global _seen_bootstrapped
    if _seen_bootstrapped:
        return
    _seen_bootstrapped = True
    from tempa.channels.whatsapp.conversation import get_recent_messages as _get

    msgs = _get(500)
    for i, row in enumerate(msgs):
        mid = row.get("id")
        if row.get("role") != "user" or not mid:
            continue
        for later in msgs[i + 1 : i + 8]:
            if later.get("role") == "user":
                break
            if later.get("role") == "assistant":
                _seen_message_ids.add(str(mid))
                break


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
        from tempa.channels.whatsapp.conversation import has_assistant_reply_for
        from tempa.channels.whatsapp.numbers import get_bridge_whatsapp_phone, remember_message_lid_mapping

        _bootstrap_seen_from_history()
        bootstrap_dedupe()

        for out in parse_outbound_messages_upsert(payload):
            remember_message_lid_mapping(out.raw_item)
            key = out.message_id or f"out:{out.chat_id}:{out.text}"
            if not _mark_seen(key):
                continue
            record_conversation_turn(
                role="owner",
                text=out.text,
                from_number=get_bridge_whatsapp_phone() or "owner",
                message_id=out.message_id,
                chat_id=out.chat_id,
            )

        messages = parse_messages_upsert(payload)
        queued = 0
        for msg in messages:
            remember_message_lid_mapping(msg.raw_item)
            if msg.message_id and has_assistant_reply_for(msg.message_id):
                continue
            if msg.timestamp:
                age = int(time.time()) - int(msg.timestamp)
                if age > _MAX_MESSAGE_AGE_SECONDS:
                    logger.warning(
                        "Dropped stale WhatsApp message %s (age %ds)",
                        msg.message_id,
                        age,
                    )
                    continue
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
            data={"state": state, "connected": snapshot.get("connected"), "instance": model.instance},
            hypothesis_id="H2",
        )
        # #endregion
        if str(state).lower() in {"open", "connected"}:
            from tempa.channels.whatsapp.session import clear_qr_code
            from tempa.channels.whatsapp.numbers import sync_linked_owner_from_bridge

            await asyncio.to_thread(clear_qr_code)
            asyncio.create_task(sync_linked_owner_from_bridge())
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
            code = qrcode.get("code")
            # Bridge/Evolution sometimes put the raw WA pairing string in `base64`, not PNG data.
            if isinstance(base64_qr, str) and base64_qr and ("@" in base64_qr or len(base64_qr) < 500):
                # #region agent log
                agent_log(
                    location="webhook.py:qrcode_updated:reject_base64",
                    message="ignored invalid base64 field — will render from code",
                    data={"base64_len": len(base64_qr), "has_code": bool(code)},
                    hypothesis_id="H8",
                )
                # #endregion
                base64_qr = None
            if not (isinstance(base64_qr, str) and base64_qr):
                if isinstance(code, str) and code:
                    base64_qr = await asyncio.to_thread(
                        WhatsAppBridgeClient._qr_image_from_code, code
                    )
            if isinstance(base64_qr, str) and base64_qr:
                if not base64_qr.startswith("data:"):
                    base64_qr = f"data:image/png;base64,{base64_qr}"
                if len(base64_qr) < 500:
                    # #region agent log
                    agent_log(
                        location="webhook.py:qrcode_updated:reject_short",
                        message="ignored QR — too short to be a scannable image",
                        data={"qr_len": len(base64_qr)},
                        hypothesis_id="H8",
                    )
                    # #endregion
                    return
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
