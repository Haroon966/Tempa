from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def max_parallel_workers() -> int:
    from tempa.orchestrator.config import load_orchestrator_config

    return max(1, int(load_orchestrator_config().max_parallel_workers or 4))


async def gather_limited(coros: list[Coroutine[Any, Any, T] | Awaitable[T]]) -> list[T]:
    """asyncio.gather with orchestrator max_parallel_workers semaphore."""
    if not coros:
        return []
    limit = max_parallel_workers()
    if len(coros) <= limit:
        return list(await asyncio.gather(*coros))

    sem = asyncio.Semaphore(limit)

    async def _run(coro: Coroutine[Any, Any, T] | Awaitable[T]) -> T:
        async with sem:
            return await coro

    return list(await asyncio.gather(*(_run(c) for c in coros)))
