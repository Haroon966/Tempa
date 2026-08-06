"""Tempa interactive Slack adapter — full-thread agent behind Tempa face."""

from __future__ import annotations

import logging
from typing import Any

from tempa.agent.runner import (
    begin_thread_run,
    cancel_thread_run,
    claim_thread_lock,
    handle_interactive_turn,
    is_cancel_request,
    tempa_agent_available,
)
from tempa.agent.sessions import get_session, save_session
from tempa.agent.slack_activity import SlackActivityFeed
from tempa.channels.slack.cursor_progress import msg_stopped, msg_unavailable
from tempa.channels.slack.outbound import send_slack_message
from tempa.channels.slack.users import is_privileged_slack_user
from tempa.orchestrator.routing import is_coding_work_request

logger = logging.getLogger(__name__)


async def run_slack_tempa_turn(
    *,
    text: str,
    user_id: str,
    channel_id: str,
    thread_ts: str,
    reply_thread: str,
    slack_ctx: dict[str, Any],
    say=None,
) -> dict[str, Any]:
    """Handle one Slack interactive message via Tempa agent (permanent path)."""
    privileged = is_privileged_slack_user(user_id)

    if is_cancel_request(text):
        cancelled = cancel_thread_run(channel=channel_id, thread_id=thread_ts)
        reply = msg_stopped() if cancelled else "_Nothing running to stop._"
        await _post(channel_id, reply, reply_thread=reply_thread, say=say)
        return {"handled": 1, "reply": reply, "cancelled": cancelled}

    if not tempa_agent_available():
        reply = msg_unavailable()
        await _post(channel_id, reply, reply_thread=reply_thread, say=say)
        return {"handled": 1, "reply": reply, "error": "agent_unavailable"}

    # Guests cannot run coding / Coolify / PC — permanent privilege gate.
    if not privileged:
        from tempa.agents.intent import wants_private_integrations
        from tempa.channels.coolify.intent import wants_coolify_deploy
        from tempa.channels.slack.messages import GUEST_CODING_DENIED, GUEST_PRIVATE_COMING_SOON

        if is_coding_work_request(text, slack_ctx) or wants_coolify_deploy(text):
            await _post(channel_id, GUEST_CODING_DENIED, reply_thread=reply_thread, say=say)
            return {"handled": 1, "reply": GUEST_CODING_DENIED, "denied": True}
        if wants_private_integrations(text):
            await _post(channel_id, GUEST_PRIVATE_COMING_SOON, reply_thread=reply_thread, say=say)
            return {"handled": 1, "reply": GUEST_PRIVATE_COMING_SOON, "denied": True}

    lock = claim_thread_lock(channel=channel_id, thread_id=thread_ts)
    async with lock:
        # Ownership before first status so mid-run follow-ups without @mention still route.
        prior = get_session(channel=channel_id, thread_id=thread_ts)
        save_session(
            channel=channel_id,
            thread_id=thread_ts,
            agent_id=str((prior or {}).get("agent_id") or "pending"),
            user_id=user_id,
        )

        # Register pending before status so stop/cancel during setup is honored.
        if not begin_thread_run(channel=channel_id, thread_id=thread_ts):
            reply = msg_stopped()
            await _post(channel_id, reply, reply_thread=reply_thread, say=say)
            return {"handled": 1, "reply": reply, "cancelled": True}

        # Flat DMs: reply_thread is "" — never pass channel id as Slack thread_ts.
        feed = SlackActivityFeed(
            channel_id=channel_id,
            thread_ts=reply_thread,
            say=say,
        )
        await feed.ensure_status()

        async def on_activity(steps: list[str], done: bool) -> None:
            await feed.update(steps, done=done)

        result = await handle_interactive_turn(
            user_message=text,
            channel=channel_id,
            thread_id=thread_ts,
            user_id=user_id,
            channel_kind="slack",
            extra_context=dict(slack_ctx or {}),
            on_activity=on_activity,
            already_locked=True,
        )
    reply = str(result.get("reply") or "").strip() or "_Done._"
    await _post(channel_id, reply, reply_thread=reply_thread, say=say)
    return {
        "handled": 1,
        "reply": reply,
        "ok": bool(result.get("ok")),
        "tempa_agent": True,
        **{k: result[k] for k in ("agent_id", "local_cwd", "repo", "error") if k in result},
    }


async def _post(channel_id: str, text: str, *, reply_thread: str, say=None) -> None:
    from tempa.channels.slack.formatting import prepare_slack_reply
    from tempa.channels.slack.outbound import _split_text

    formatted = prepare_slack_reply(text)
    chunks = _split_text(formatted)
    if say is not None:
        for chunk in chunks:
            kwargs: dict[str, Any] = {"text": chunk}
            if reply_thread:
                kwargs["thread_ts"] = reply_thread
            await say(**kwargs)
        return
    await send_slack_message(
        channel_id,
        text,
        thread_ts=reply_thread,
        source_channel="tempa_agent",
    )
