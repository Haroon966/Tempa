from __future__ import annotations

import asyncio
import logging
import time

from playwright.async_api import Page

from tempa.meet.joiner import _in_waiting_room, _is_in_active_call
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


async def notify_owner_admit_tempa(*, meet_url: str, title: str = "") -> None:
    """Ask the owner to admit Tempa when Meet shows the waiting room."""
    slug = meet_url.rstrip("/").split("/")[-1]
    label = (title or slug).strip()
    msg = (
        f"Tempa is waiting to join *{label}*.\n"
        f"Meet link: {meet_url}\n\n"
        "Open Google Meet → Participants → admit *Tempa* (or tap the green check)."
    )

    from tempa.channels.whatsapp.reply import load_default_whatsapp_number

    settings = get_settings()
    number = load_default_whatsapp_number()
    if number:
        try:
            from tempa.channels.whatsapp.outbound import send_whatsapp_message

            await send_whatsapp_message(number, msg, source_channel="whatsapp_auto_reply")
        except Exception:
            logger.debug("WhatsApp admission notify failed", exc_info=True)

    if settings.meet_auto_send_summary_slack and settings.slack_owner_user_id.strip():
        try:
            from tempa.channels.slack.formatting import prepare_slack_reply
            from tempa.channels.slack.outbound import open_dm_for_user, send_slack_message

            channel_id = await open_dm_for_user(settings.slack_owner_user_id.strip())
            await send_slack_message(
                channel_id,
                prepare_slack_reply(msg),
                source_channel="slack_auto_reply",
            )
        except Exception:
            logger.debug("Slack admission notify failed", exc_info=True)


async def wait_for_meet_admission(
    page: Page,
    *,
    meet_url: str,
    title: str = "",
    timeout_s: float | None = None,
    remind_every_s: float = 90.0,
) -> bool:
    """Wait for host admission, reminding the owner periodically."""
    settings = get_settings()
    limit = float(timeout_s if timeout_s is not None else settings.meet_admission_timeout_seconds)

    if await _is_in_active_call(page):
        logger.info("GMEET: already in call, skipping admission wait")
        return True

    if not await _in_waiting_room(page):
        # Pre-join or transitioning — brief pause before notifying.
        await asyncio.sleep(2.0)
        if await _is_in_active_call(page):
            logger.info("GMEET: admitted to meeting during pre-check")
            return True

    await notify_owner_admit_tempa(meet_url=meet_url, title=title)

    deadline = time.monotonic() + limit
    last_remind = time.monotonic()
    poll_s = 2.0
    logger.info("GMEET: waiting for host admission (timeout=%.0fs)", limit)

    while time.monotonic() < deadline:
        if time.monotonic() - last_remind >= remind_every_s:
            await notify_owner_admit_tempa(meet_url=meet_url, title=title)
            last_remind = time.monotonic()

        if await _in_waiting_room(page):
            await asyncio.sleep(poll_s)
            continue

        if await _is_in_active_call(page):
            logger.info("GMEET: admitted to meeting (in-call UI detected)")
            return True

        # Not in waiting room and not in call yet — keep polling without spamming.
        await asyncio.sleep(poll_s)

    logger.warning("GMEET: admission timeout after %.0fs", limit)
    return False
