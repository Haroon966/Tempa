from __future__ import annotations

import asyncio
from typing import Any

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop


def schedule_coro(coro: Any) -> asyncio.Task | None:
    """Schedule a coroutine on the daemon's main loop (safe from sync threads)."""
    loop = _main_loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(coro)
        except RuntimeError:
            return None
    return asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]
