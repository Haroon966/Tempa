from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from tempa.channels.whatsapp.reply import handle_inbound_whatsapp
from tempa.channels.whatsapp.schemas import WhatsAppMessage
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_REPLY_TIMEOUT_SECONDS = 45.0
_queue: asyncio.Queue[WhatsAppMessage | None] | None = None
_worker_task: asyncio.Task | None = None
_inflight: set[str] = set()


def _actions_path() -> Path:
    path = get_settings().sessions_dir / "action_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_persisted_actions() -> dict[str, Any]:
    path = _actions_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load action state: %s", exc)
        return {}


def save_persisted_actions(data: dict[str, Any]) -> None:
    path = _actions_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def _dispatch(msg: WhatsAppMessage) -> None:
    key = msg.message_id or f"{msg.from_number}:{msg.chat_id}:{msg.text}"
    if key in _inflight:
        return
    _inflight.add(key)
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
        _inflight.discard(key)


async def _worker_loop() -> None:
    assert _queue is not None
    while True:
        msg = await _queue.get()
        if msg is None:
            _queue.task_done()
            break
        try:
            await _dispatch(msg)
        finally:
            _queue.task_done()


async def start_inbound_worker() -> None:
    global _queue, _worker_task
    if _worker_task and not _worker_task.done():
        return
    _queue = asyncio.Queue(maxsize=200)
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("WhatsApp inbound worker started")


async def stop_inbound_worker() -> None:
    global _queue, _worker_task
    if _queue is not None:
        await _queue.put(None)
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=30)
        except asyncio.TimeoutError:
            _worker_task.cancel()
    _worker_task = None
    _queue = None
    _inflight.clear()


async def enqueue_inbound(msg: WhatsAppMessage) -> bool:
    if _queue is None:
        await start_inbound_worker()
    assert _queue is not None
    try:
        _queue.put_nowait(msg)
        return True
    except asyncio.QueueFull:
        logger.error("WhatsApp inbound queue full — dropping message %s", msg.message_id)
        return False
