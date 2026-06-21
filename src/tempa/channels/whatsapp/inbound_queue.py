from __future__ import annotations

import asyncio
import logging

from tempa.channels.whatsapp.reply import handle_inbound_whatsapp
from tempa.channels.whatsapp.schemas import WhatsAppMessage

logger = logging.getLogger(__name__)

_REPLY_TIMEOUT_SECONDS = 45.0
_inflight: set[str] = set()
_dispatch_sem = asyncio.Semaphore(1)


async def _dispatch(msg: WhatsAppMessage) -> None:
    key = msg.message_id or f"{msg.from_number}:{msg.chat_id}:{msg.text}"
    if key in _inflight:
        return
    _inflight.add(key)
    try:
        async with _dispatch_sem:
            await asyncio.wait_for(
            handle_inbound_whatsapp(
                msg.from_number,
                msg.text,
                msg.message_id,
                chat_id=msg.chat_id,
                is_group=msg.is_group,
                raw_item=msg.raw_item,
            ),
            timeout=_REPLY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            "WhatsApp inbound timed out after %.0fs (message %s)",
            _REPLY_TIMEOUT_SECONDS,
            msg.message_id,
        )
        try:
            from tempa.channels.whatsapp.outbound import send_whatsapp_message

            target = msg.chat_id if msg.chat_id and "@" in msg.chat_id else msg.from_number
            await send_whatsapp_message(
                target,
                "Sorry — that took too long. Please try again.",
                source_channel="whatsapp_auto_reply",
            )
        except Exception:
            logger.exception("Failed to send WhatsApp timeout notice")
    except Exception:
        logger.exception("WhatsApp inbound processing failed")
    finally:
        _inflight.discard(key)


async def start_inbound_worker() -> None:
    """No-op — kept for startup compatibility."""


async def stop_inbound_worker() -> None:
    _inflight.clear()


async def enqueue_inbound(msg: WhatsAppMessage) -> bool:
    await _dispatch(msg)
    return True
