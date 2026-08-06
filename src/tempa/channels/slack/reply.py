from __future__ import annotations

import logging
import re
import threading

from tempa.channels.slack.context import is_dm_event, reply_thread_ts
from tempa.channels.slack.conversation import (
    conversation_thread_key,
    has_assistant_reply_for,
    record_conversation_turn,
)
from tempa.channels.slack.ingest import ingest_slack_message
from tempa.channels.slack.session import mark_inbound_seen, set_error, touch_event
from tempa.channels.slack.users import is_privileged_slack_user
from tempa.core.events import event_bus

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


def _schedule_ingest(
    event: dict,
    *,
    user_id: str,
    channel_id: str,
    user_names: dict[str, str] | None = None,
) -> None:
    """Fire-and-forget ingest on a daemon thread (must not block pytest / event loop shutdown)."""
    threading.Thread(
        target=_ingest_inbound,
        kwargs={"event": event, "user_id": user_id, "channel_id": channel_id, "user_names": user_names},
        daemon=True,
    ).start()


def _ingest_inbound(
    event: dict,
    *,
    user_id: str,
    channel_id: str,
    user_names: dict[str, str] | None = None,
) -> None:
    try:
        ingest_slack_message(
            event,
            channel_id=channel_id,
            user_names=user_names,
            tags=["inbound"],
        )
    except Exception:
        logger.exception("Failed to index Slack message")


def _normalize_text(text: str, *, event_type: str) -> str:
    _ = event_type
    cleaned = _MENTION_RE.sub("", text or "").strip()
    cleaned = re.sub(r"<(https?://[^>|]+)(?:\|[^>]+)?>", r"\1", cleaned)
    return cleaned.strip()


async def handle_inbound_slack(
    event: dict,
    *,
    event_type: str = "message",
    event_id: str = "",
    say=None,
) -> dict:
    """Route Slack DM or @mention to Tempa agent (Cursor engine) and post a reply.

    Permanent cutover: interactive messages no longer use the Groq coordinator chat brain.
    Auto Meet STT/minutes stay on Groq outside this path.
    """
    if not mark_inbound_seen(
        event_id=event_id,
        channel_id=str(event.get("channel") or ""),
        message_ts=str(event.get("ts") or ""),
    ):
        return {"handled": 0, "duplicate": True, "event_id": event_id}

    touch_event()

    if event.get("bot_id") or event.get("subtype"):
        return {"handled": 0, "skipped": "bot_or_subtype"}

    user_id = str(event.get("user") or "")
    channel_id = str(event.get("channel") or "")
    message_ts = str(event.get("ts") or "")
    thread_ts = str(event.get("thread_ts") or message_ts)
    is_dm = is_dm_event(event)
    conv_key = conversation_thread_key(channel_id=channel_id, thread_ts=thread_ts, is_dm=is_dm)
    text = _normalize_text(str(event.get("text") or ""), event_type=event_type)

    if not user_id or not channel_id or not text:
        return {"handled": 0, "skipped": "empty"}

    if message_ts and has_assistant_reply_for(message_ts):
        return {"handled": 0, "duplicate": True, "message_id": message_ts}

    reply_thread = reply_thread_ts(event, event_type=event_type)
    slack_privileged = is_privileged_slack_user(user_id)

    _schedule_ingest(event, user_id=user_id, channel_id=channel_id)

    from tempa.channels.slack.varys_bridge import enrich_slack_context

    slack_ctx = enrich_slack_context(event, {"slack_privileged": slack_privileged})
    slack_ctx["slack_message_ts"] = message_ts
    slack_ctx["user_id"] = user_id
    slack_ctx["channel_id"] = channel_id

    # Rumi capability inventory — no agent run (fast, deterministic).
    from tempa.orchestrator.routing import is_rumi_capability_ask

    if is_rumi_capability_ask(text, slack_ctx):
        from tempa.channels.slack.rumi_pack import format_rumi_capability_reply

        cap_reply = format_rumi_capability_reply()
        from tempa.agent.slack_ingress import _post

        await _post(channel_id, cap_reply, reply_thread=reply_thread, say=say)
        record_conversation_turn(
            role="user",
            text=text,
            user_id=user_id,
            channel_id=channel_id,
            message_id=message_ts,
            thread_ts=thread_ts,
            conversation_key=conv_key,
        )
        record_conversation_turn(
            role="assistant",
            text=cap_reply,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=reply_thread,
            conversation_key=conv_key,
        )
        return {
            "handled": 1,
            "reply": cap_reply,
            "skipped_coordinator": True,
            "user": user_id,
            "channel": channel_id,
            "rumi_capability": True,
        }

    # Deterministic confirm UXs (not a chat LLM) — Coolify deploy + Jira ticket drafts.
    from tempa.channels.coolify.deploy import (
        deploy_feature_enabled,
        handle_coolify_deploy_message,
        should_route_to_coolify_deploy,
    )
    from tempa.channels.jira.tickets import (
        handle_jira_ticket_message,
        should_route_to_jira_ticket,
        ticket_feature_enabled,
    )

    if deploy_feature_enabled() and should_route_to_coolify_deploy(text, slack_ctx):
        if not slack_privileged:
            from tempa.channels.slack.messages import GUEST_DEPLOY_DENIED
            from tempa.agent.slack_ingress import _post

            await _post(channel_id, GUEST_DEPLOY_DENIED, reply_thread=reply_thread, say=say)
            record_conversation_turn(
                role="user",
                text=text,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_ts,
                thread_ts=thread_ts,
                conversation_key=conv_key,
            )
            record_conversation_turn(
                role="assistant",
                text=GUEST_DEPLOY_DENIED,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=reply_thread,
                conversation_key=conv_key,
            )
            return {
                "handled": 1,
                "reply": GUEST_DEPLOY_DENIED,
                "user": user_id,
                "channel": channel_id,
                "denied": True,
                "coolify_denied": True,
            }
        coolify_reply = await handle_coolify_deploy_message(text, slack_ctx)
        if coolify_reply:
            from tempa.agent.slack_ingress import _post

            await _post(channel_id, coolify_reply, reply_thread=reply_thread, say=say)
            record_conversation_turn(
                role="user",
                text=text,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_ts,
                thread_ts=thread_ts,
                conversation_key=conv_key,
            )
            record_conversation_turn(
                role="assistant",
                text=coolify_reply,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=reply_thread,
                conversation_key=conv_key,
            )
            return {
                "handled": 1,
                "reply": coolify_reply,
                "user": user_id,
                "channel": channel_id,
                "coolify_deploy": True,
            }

    if ticket_feature_enabled() and should_route_to_jira_ticket(text, slack_ctx):
        ticket_reply = await handle_jira_ticket_message(text, slack_ctx)
        if ticket_reply:
            from tempa.agent.slack_ingress import _post

            await _post(channel_id, ticket_reply, reply_thread=reply_thread, say=say)
            record_conversation_turn(
                role="user",
                text=text,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_ts,
                thread_ts=thread_ts,
                conversation_key=conv_key,
            )
            record_conversation_turn(
                role="assistant",
                text=ticket_reply,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=reply_thread,
                conversation_key=conv_key,
            )
            return {
                "handled": 1,
                "reply": ticket_reply,
                "user": user_id,
                "channel": channel_id,
                "jira_ticket": True,
            }

    # Durable coding / Rumi agent jobs — Cursor worker (worktree, PR, CI). Not chat brain.
    from tempa.channels.slack.cursor_threads import (
        ambiguous_repo_message,
        cursor_owns_coding,
        handle_cursor_job_message,
        is_cursor_thread,
        resolve_cursor_job_cfg,
        rumi_agent_job_cfg,
    )
    from tempa.channels.slack.messages import GUEST_CODING_DENIED
    from tempa.orchestrator.routing import is_coding_work_request
    from tempa.rumi.classify import classify_rumi

    # DMs: durable jobs + pins use channel id (same as interactive session key).
    job_thread_ts = conv_key if is_dm else thread_ts
    if is_dm:
        slack_ctx["slack_thread_ts"] = job_thread_ts
        slack_ctx["thread_ts"] = job_thread_ts
        slack_ctx["slack_conversation_key"] = conv_key

    pinned = is_cursor_thread(channel_id, job_thread_ts)
    rumi_kind = classify_rumi(text)
    rumi_ask = cursor_owns_coding() and rumi_kind == "agent"
    # Pin alone is not enough — casual "what's left?" stays on the interactive agent.
    # Coding follow-ups inherit repo via is_coding_work_request + thread context.
    coding = (not rumi_ask) and cursor_owns_coding() and is_coding_work_request(
        text, slack_ctx
    )
    if rumi_ask or coding:
        from tempa.agent.slack_ingress import _post

        if not slack_privileged:
            await _post(channel_id, GUEST_CODING_DENIED, reply_thread=reply_thread, say=say)
            record_conversation_turn(
                role="user",
                text=text,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_ts,
                thread_ts=thread_ts,
                conversation_key=conv_key,
            )
            record_conversation_turn(
                role="assistant",
                text=GUEST_CODING_DENIED,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=reply_thread,
                conversation_key=conv_key,
            )
            return {
                "handled": 1,
                "reply": GUEST_CODING_DENIED,
                "user": user_id,
                "channel": channel_id,
                "denied": True,
                "cursor_denied": True,
            }
        if rumi_ask:
            cfg = rumi_agent_job_cfg()
            cursor_reply = await handle_cursor_job_message(text, slack_ctx, cfg=cfg)
            if cursor_reply is None:
                cursor_reply = "_Something went wrong starting that job — please ask again in a moment._"
        else:
            cfg = resolve_cursor_job_cfg(
                text, channel_id=channel_id, thread_ts=job_thread_ts
            )
            if cfg is None and not pinned:
                cursor_reply = ambiguous_repo_message()
            elif cfg is None:
                cursor_reply = "_Something went wrong starting that job — please ask again in a moment._"
            else:
                cursor_reply = await handle_cursor_job_message(text, slack_ctx, cfg=cfg)
                if cursor_reply is None:
                    cursor_reply = "_Something went wrong starting that job — please ask again in a moment._"
        await _post(channel_id, cursor_reply, reply_thread=reply_thread, say=say)
        record_conversation_turn(
            role="user",
            text=text,
            user_id=user_id,
            channel_id=channel_id,
            message_id=message_ts,
            thread_ts=thread_ts,
            conversation_key=conv_key,
        )
        record_conversation_turn(
            role="assistant",
            text=cursor_reply,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=reply_thread,
            conversation_key=conv_key,
        )
        return {
            "handled": 1,
            "reply": cursor_reply,
            "user": user_id,
            "channel": channel_id,
            "cursor_thread": pinned,
            "cursor_coding": not rumi_ask,
            "rumi_agent": rumi_ask,
        }

    record_conversation_turn(
        role="user",
        text=text,
        user_id=user_id,
        channel_id=channel_id,
        message_id=message_ts,
        thread_ts=thread_ts,
        conversation_key=conv_key,
    )

    from tempa.agent.slack_ingress import run_slack_tempa_turn

    # DMs: one agent session per channel so create/resume works across turns.
    agent_thread_id = channel_id if is_dm else thread_ts

    try:
        outcome = await run_slack_tempa_turn(
            text=text,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=agent_thread_id,
            reply_thread=reply_thread,
            slack_ctx=slack_ctx,
            say=say,
        )
    except Exception as exc:
        logger.exception("Slack Tempa agent turn failed")
        from tempa.channels.slack.cursor_progress import msg_problem

        reply = msg_problem(exc)
        from tempa.agent.slack_ingress import _post

        await _post(channel_id, reply, reply_thread=reply_thread, say=say)
        set_error(str(exc)[:200])
        outcome = {"handled": 1, "reply": reply, "error": "exception"}

    reply = str(outcome.get("reply") or "")
    record_conversation_turn(
        role="assistant",
        text=reply,
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=reply_thread,
        conversation_key=conv_key,
    )
    await event_bus.publish_json("channel", "slack_reply", user_id)
    set_error(None)
    return {
        "handled": 1,
        "reply": reply,
        "user": user_id,
        "channel": channel_id,
        "tempa_agent": True,
        **{k: outcome[k] for k in ("ok", "denied", "cancelled", "error", "agent_id") if k in outcome},
    }
