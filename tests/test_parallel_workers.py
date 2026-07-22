from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from tempa.orchestrator.parallel import gather_limited


@pytest.mark.asyncio
async def test_gather_limited_respects_semaphore():
    current = 0
    peak = 0

    async def work(_i: int) -> int:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.02)
        current -= 1
        return _i

    with patch("tempa.orchestrator.parallel.max_parallel_workers", return_value=2):
        results = await gather_limited([work(i) for i in range(5)])

    assert results == [0, 1, 2, 3, 4]
    assert peak <= 2
