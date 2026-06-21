from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tempa.channels.whatsapp.reply import handle_inbound_whatsapp
from tempa.channels.whatsapp.schemas import WhatsAppMessage

logger = logging.getLogger(__name__)

_queue: asyncio.PriorityQueue[tuple[int, int, WhatsAppMessage]] | None = None
_worker_task: asyncio.Task | None = None
_enqueue_seq = 0


_REPLY_TIMEOUT_SECONDS = 45.0


async def _worker() -> None:
    assert _queue is not None
    while True:
        _prio, _seq, msg = await _queue.get()
        try:
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
            _queue.task_done()


async def start_inbound_worker() -> None:
    global _queue, _worker_task
    if _worker_task is not None:
        return
    _queue = asyncio.PriorityQueue(maxsize=200)
    _worker_task = asyncio.create_task(_worker(), name="whatsapp-inbound-worker")


async def stop_inbound_worker() -> None:
    global _worker_task, _queue
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    _queue = None


async def enqueue_inbound(msg: WhatsAppMessage) -> bool:
    global _enqueue_seq
    if _queue is None:
        await start_inbound_worker()
    assert _queue is not None
    try:
        ts = msg.timestamp or int(time.time())
        _enqueue_seq += 1
        _queue.put_nowait((-ts, _enqueue_seq, msg))
        return True
    except asyncio.QueueFull:
        logger.warning("WhatsApp inbound queue full; dropping message %s", msg.message_id)
        return False
