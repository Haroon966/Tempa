"""Dashboard payload response cache."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from tempa.api import dashboard as dash


@pytest.mark.asyncio
async def test_payload_cache_hit_skips_rebuild():
    dash._cache_clear()
    fake = {"generated_at": "old", "overall": {"status": "healthy"}}

    with patch.object(dash, "_build_dashboard_payload_uncached", new_callable=AsyncMock) as uncached:
        uncached.return_value = fake
        first = await dash.build_dashboard_payload()
        second = await dash.build_dashboard_payload()

    assert uncached.await_count == 1
    assert first["overall"] == second["overall"]
    assert second["generated_at"] != "old"


@pytest.mark.asyncio
async def test_refresh_clears_payload_cache():
    dash._cache_clear()
    fake = {"generated_at": "t", "overall": {}}

    with patch.object(dash, "_build_dashboard_payload_uncached", new_callable=AsyncMock) as uncached:
        uncached.return_value = fake
        await dash.build_dashboard_payload()
        await dash.build_dashboard_payload(refresh=True)
        await dash.build_dashboard_payload()

    assert uncached.await_count == 2


def test_payload_cache_expires():
    dash._cache_clear()
    dash._payload_cache_set({"generated_at": "t", "overall": {}})
    dash._payload_cache = (time.monotonic() - dash._PAYLOAD_TTL - 1, dash._payload_cache[1])
    assert dash._payload_cache_get() is None
