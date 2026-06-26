from __future__ import annotations

import logging
from typing import Any

from tempa.settings import get_settings
from tempa.varys import harness
from tempa.varys.config import load_varys_config
from tempa.varys.context import build_context
from tempa.varys.manager import is_go_signal, is_work_request
from tempa.varys.prefetch import prefetch_tool_context
from tempa.varys.runner import run_claude_prompt
from tempa.varys.tools import invoke_runtime_tools
from tempa.varys.vault_sync import append_session_log, ensure_vault_initialized

logger = logging.getLogger(__name__)


async def run_varys_coordinator(
    user_message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = dict(context or {})
    cfg = load_varys_config()
    settings = get_settings()
    ensure_vault_initialized()

    channel = str(ctx.get("channel") or "dashboard")
    slack_user = str(ctx.get("slack_user_id") or "")
    thread_ts = str(ctx.get("slack_thread_ts") or ctx.get("thread_ts") or "")

    def _is_owner() -> bool:
        if channel == "slack":
            owner_id = cfg.owner_slack_user_id or settings.slack_owner_user_id
            return bool(owner_id and slack_user == owner_id)
        if channel == "whatsapp":
            owner = (settings.whatsapp_owner_number or "").strip()
            sender = str(ctx.get("whatsapp_number") or ctx.get("from_number") or "")
            return bool(owner and sender and owner in sender)
        return channel == "dashboard"

    db = harness.get_db()
    pending_actions: list[dict[str, Any]] = []
    paused = False

    try:
        if is_go_signal(user_message) and _is_owner():
            origin = f"{ctx.get('slack_channel_id', channel)}-{thread_ts or 'main'}"
            entity_id = harness.register_entity(db, channel, origin, "thread")
            harness.insert_event(
                db,
                event_id=f"{channel}-go-{thread_ts or 'main'}-{user_message[:20]}",
                source=channel,
                event_type="message.go_signal",
                context_key=entity_id,
                payload={"thread_ts": thread_ts, "channel": ctx.get("slack_channel_id", channel)},
                priority="high",
            )
            return {
                "response": "Approved — I'll proceed with the plan on the next orchestrator tick.",
                "sources": [],
                "paused": False,
                "pending_actions": [],
                "artifacts": [],
            }
        if is_go_signal(user_message):
            return {
                "response": "Only the owner can approve with go/approve.",
                "sources": [],
                "paused": False,
                "pending_actions": [],
                "artifacts": [],
            }

        if is_work_request(user_message):
            ticket_id = harness.create_ticket(
                db,
                title=user_message[:200],
                origin_channel=channel,
                origin_thread=thread_ts,
                payload={"message": user_message, **{k: v for k, v in ctx.items() if k.startswith("slack_")}},
            )
            from tempa.core.pending_actions import create_pending_action

            action = create_pending_action(
                "varys_ticket",
                {
                    "ticket_id": ticket_id,
                    "title": user_message[:200],
                    "origin_channel": channel,
                    "origin_thread": thread_ts,
                    "message": user_message,
                },
                source_channel=channel,
                risk_level="medium",
                title=user_message[:200],
            )
            reply = (
                f"Logged work ticket `{ticket_id}`. I'll draft a plan and wait for your approval "
                f"(reply **go** or approve in the dashboard when ready to implement)."
            )
            append_session_log(f"Work ticket created: {ticket_id} — {user_message[:120]}")
            return {
                "response": reply,
                "sources": [],
                "paused": True,
                "pending_actions": [
                    {
                        "id": action["id"],
                        "type": "varys_ticket",
                        "preview": user_message[:500],
                    }
                ],
                "artifacts": [{"type": "varys_ticket", "ticket_id": ticket_id}],
            }

        built = build_context(user_message, ctx)
        prefetch = await prefetch_tool_context(user_message, ctx)
        runtime = await invoke_runtime_tools(user_message, ctx)

        from tempa.channels.jira.direct_reply import try_jira_direct_reply

        jira_direct = await try_jira_direct_reply(user_message, ctx)
        if jira_direct:
            append_session_log(f"[{channel}] Q: {user_message[:80]}")
            return {
                "response": jira_direct,
                "sources": [],
                "paused": paused,
                "pending_actions": pending_actions,
                "artifacts": [],
            }

        from tempa.channels.slack.direct_reply import try_slack_direct_reply

        direct = await try_slack_direct_reply(user_message, ctx)
        if direct:
            append_session_log(f"[{channel}] Q: {user_message[:80]}")
            return {
                "response": direct,
                "sources": built.get("sources") or [],
                "paused": paused,
                "pending_actions": pending_actions,
                "artifacts": [],
            }

        tool_blocks = "\n\n".join(block for block in (prefetch, runtime) if block)
        if tool_blocks:
            built["system"] = (
                built["system"] + "\n\n## Live tool results (use these — do not invent data)\n" + tool_blocks
            )
        try:
            reply = await run_claude_prompt(system=built["system"], user=built["user"])
        except Exception as exc:
            logger.exception("Varys coordinator LLM failed")
            reply = f"I couldn't reach the Claude runner ({exc}). Check ANTHROPIC_API_KEY or Claude Code CLI."

        append_session_log(f"[{channel}] Q: {user_message[:80]}")
        return {
            "response": reply.strip(),
            "sources": built.get("sources") or [],
            "paused": paused,
            "pending_actions": pending_actions,
            "artifacts": [],
        }
    finally:
        db.close()
