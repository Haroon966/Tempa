from __future__ import annotations

import asyncio
import logging
from typing import Any

from tempa.channels.whatsapp.reply import handle_inbound_whatsapp
from tempa.channels.whatsapp.schemas import WhatsAppMessage

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[WhatsAppMessage] | None = None
_worker_task: asyncio.Task | None = None


async def _worker() -> None:
    assert _queue is not None
    while True:
        msg = await _queue.get()
        try:
            await handle_inbound_whatsapp(
                msg.from_number,
                msg.text,
                msg.message_id,
                chat_id=msg.chat_id,
                is_group=msg.is_group,
                raw_item=msg.raw_item,
            )
        except Exception:
            logger.exception("WhatsApp inbound processing failed")
        finally:
            _queue.task_done()


async def start_inbound_worker() -> None:
    global _queue, _worker_task
    if _worker_task is not None:
        return
    _queue = asyncio.Queue(maxsize=200)
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
    if _queue is None:
        await start_inbound_worker()
    assert _queue is not None
    try:
        _queue.put_nowait(msg)
        return True
    except asyncio.QueueFull:
        logger.warning("WhatsApp inbound queue full; dropping message %s", msg.message_id)
        return False
