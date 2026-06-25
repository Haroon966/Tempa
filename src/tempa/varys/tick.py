from __future__ import annotations

import asyncio
import logging
from typing import Any

from tempa.settings import get_settings
from tempa.varys.dispatch import run_tick

logger = logging.getLogger(__name__)

_tick_task: asyncio.Task | None = None


async def varys_tick_loop() -> None:
    settings = get_settings()
    interval = max(30, settings.varys_tick_seconds)
    logger.info("Varys orchestrator tick loop started (interval=%ss)", interval)
    while True:
        try:
            result = await asyncio.to_thread(run_tick)
            if result.get("dispatched"):
                logger.info("Varys tick dispatched %s sessions", result.get("dispatched"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Varys tick loop error")
        await asyncio.sleep(interval)


async def start_varys_tick_loop() -> None:
    global _tick_task
    settings = get_settings()
    if not settings.varys_orchestrator_enabled:
        return
    if _tick_task and not _tick_task.done():
        return
    _tick_task = asyncio.create_task(varys_tick_loop(), name="varys-tick")


async def stop_varys_tick_loop() -> None:
    global _tick_task
    if _tick_task:
        _tick_task.cancel()
        try:
            await _tick_task
        except asyncio.CancelledError:
            pass
        _tick_task = None
