"""Google Meet in-meeting chat automation via Playwright."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CHAT_TOGGLE_SELECTORS = [
    'button[aria-label*="Chat" i]',
    'button[data-tooltip*="Chat" i]',
    '[aria-label="Chat with everyone"]',
]

CHAT_INPUT_SELECTORS = [
    'textarea[aria-label*="message" i]',
    'textarea[placeholder*="message" i]',
    '[contenteditable="true"][aria-label*="message" i]',
    'div[role="textbox"][aria-label*="message" i]',
]

SEND_BUTTON_SELECTORS = [
    'button[aria-label*="Send" i]',
    'button[data-tooltip*="Send" i]',
]


@dataclass
class ChatMessage:
    sender: str
    text: str
    raw: str = ""


async def open_chat_panel(page: Any) -> bool:
    for selector in CHAT_TOGGLE_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    return False


async def _find_chat_input(page: Any):
    for selector in CHAT_INPUT_SELECTORS:
        loc = page.locator(selector).first
        if await loc.count() > 0 and await loc.is_visible():
            return loc
    return None


async def send_chat_message(page: Any, text: str) -> bool:
    if not text.strip():
        return False
    await open_chat_panel(page)
    inp = await _find_chat_input(page)
    if inp is None:
        logger.warning("GMEET: chat input not found")
        return False
    try:
        await inp.click()
        await inp.fill(text)
        for selector in SEND_BUTTON_SELECTORS:
            btn = page.locator(selector).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                logger.info("GMEET: sent chat message (%d chars)", len(text))
                return True
        await inp.press("Enter")
        return True
    except Exception:
        logger.exception("GMEET: failed to send chat message")
        return False


async def read_recent_messages(page: Any, limit: int = 20) -> list[ChatMessage]:
    await open_chat_panel(page)
    messages: list[ChatMessage] = []
    try:
        items = page.locator('[data-message-id], [data-message-text], div[jsname][data-sender-name]')
        count = await items.count()
        start = max(0, count - limit)
        for i in range(start, count):
            item = items.nth(i)
            text = (await item.inner_text()).strip()
            if not text:
                continue
            sender = "Unknown"
            try:
                sender_attr = await item.get_attribute("data-sender-name")
                if sender_attr:
                    sender = sender_attr
            except Exception:
                pass
            if ":" in text[:80]:
                parts = text.split(":", 1)
                if len(parts[0]) < 40:
                    sender, text = parts[0].strip(), parts[1].strip()
            messages.append(ChatMessage(sender=sender, text=text, raw=text))
    except Exception:
        logger.debug("GMEET: read chat messages fallback", exc_info=True)
    return messages
