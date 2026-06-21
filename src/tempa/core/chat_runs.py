from __future__ import annotations

import asyncio
from typing import Any

_lock = asyncio.Lock()
_active_runs: dict[str, asyncio.Event] = {}


async def register_run(run_id: str) -> asyncio.Event:
    cancel = asyncio.Event()
    async with _lock:
        _active_runs[run_id] = cancel
    return cancel


async def cancel_run(run_id: str) -> bool:
    async with _lock:
        cancel = _active_runs.get(run_id)
    if cancel is None:
        return False
    cancel.set()
    return True


async def unregister_run(run_id: str) -> None:
    async with _lock:
        _active_runs.pop(run_id, None)


def is_cancelled(cancel_event: Any) -> bool:
    return cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)()
