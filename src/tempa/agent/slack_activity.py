"""Slack live activity: edit one status message in-thread (Tempa-branded)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tempa.channels.slack.cursor_progress import msg_activity

logger = logging.getLogger(__name__)


def _extract_message_ts(payload: Any) -> str:
    """Normalize Bolt say / Web API send results to a message ts."""
    if payload is None:
        return ""
    if isinstance(payload, dict):
        direct = str(payload.get("ts") or "").strip()
        if direct:
            return direct
        nested = payload.get("result")
        if isinstance(nested, dict):
            return str(nested.get("ts") or "").strip()
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("ts") or "").strip()
    return str(getattr(payload, "ts", "") or "").strip()


class SlackActivityFeed:
    """Debounced edit-in-place activity updates for one Slack thread."""

    def __init__(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        say=None,
        min_interval_s: float = 2.0,
    ) -> None:
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self.say = say
        self.min_interval_s = min_interval_s
        self.status_ts: str | None = None
        self._last_post = 0.0
        self._pending: list[str] | None = None

    async def ensure_status(self, text: str | None = None) -> None:
        from tempa.channels.slack.cursor_progress import msg_working
        from tempa.channels.slack.outbound import send_slack_message

        body = text or msg_working()
        if self.say is not None:
            kwargs: dict[str, Any] = {"text": body}
            if self.thread_ts:
                kwargs["thread_ts"] = self.thread_ts
            resp = await self.say(**kwargs)
            self.status_ts = _extract_message_ts(resp) or None
            return
        result = await send_slack_message(
            self.channel_id,
            body,
            thread_ts=self.thread_ts,
            source_channel="tempa_agent",
        )
        self.status_ts = _extract_message_ts(result) or None

    async def update(self, steps: list[str], done: bool = False) -> None:
        now = time.monotonic()
        self._pending = list(steps)
        if not done and (now - self._last_post) < self.min_interval_s:
            return
        await self._flush(done=done)

    async def _flush(self, *, done: bool) -> None:
        steps = self._pending or []
        text = msg_activity(steps=steps, done=done)
        self._last_post = time.monotonic()
        if not self.status_ts:
            await self.ensure_status(text)
            return
        try:
            from tempa.channels.slack.client import load_slack_client

            client = load_slack_client()
            if client is None:
                return
            await asyncio_to_thread_chat_update(client, self.channel_id, self.status_ts, text)
        except Exception:
            logger.warning("activity update failed — re-posting status", exc_info=True)
            self.status_ts = None
            await self.ensure_status(text)


async def asyncio_to_thread_chat_update(client: Any, channel: str, ts: str, text: str) -> None:
    def _update() -> None:
        client.chat_update(channel=channel, ts=ts, text=text)

    await asyncio.to_thread(_update)
