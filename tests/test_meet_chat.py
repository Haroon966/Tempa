"""Tests for Meet chat automation (mocked Playwright page)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tempa.meet.chat import send_chat_message


@pytest.mark.asyncio
async def test_send_chat_message_clicks_send():
    page = MagicMock()
    btn = MagicMock()
    btn.count = AsyncMock(return_value=1)
    btn.is_visible = AsyncMock(return_value=True)
    btn.click = AsyncMock()

    inp = MagicMock()
    inp.count = AsyncMock(return_value=1)
    inp.is_visible = AsyncMock(return_value=True)
    inp.click = AsyncMock()
    inp.fill = AsyncMock()
    inp.press = AsyncMock()

    toggle = MagicMock()
    toggle.count = AsyncMock(return_value=1)
    toggle.is_visible = AsyncMock(return_value=True)
    toggle.click = AsyncMock()

    def locator_side_effect(selector: str):
        if "Chat" in selector or "chat" in selector.lower():
            return MagicMock(first=toggle)
        if "Send" in selector:
            return MagicMock(first=btn)
        return MagicMock(first=inp)

    page.locator = MagicMock(side_effect=locator_side_effect)
    page.wait_for_timeout = AsyncMock()

    ok = await send_chat_message(page, "I'll follow up by email.")
    assert ok is True
    inp.fill.assert_called_once()
