from __future__ import annotations

from typing import Any


async def go_signal_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from tempa.agents.graph import _try_go_signal_approval

    return await _try_go_signal_approval(user_message, context)


async def jira_ticket_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from tempa.agents.clarification import clarification_response
    from tempa.channels.jira.tickets import handle_jira_ticket_message, should_route_to_jira_ticket, ticket_feature_enabled

    if not ticket_feature_enabled():
        return None
    if not should_route_to_jira_ticket(user_message, context):
        return None
    ticket_reply = await handle_jira_ticket_message(user_message, context)
    if ticket_reply:
        return clarification_response(ticket_reply)
    return None


async def clarification_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from tempa.agents.clarification import clarification_response, detect_missing_context
    from tempa.channels.jira.tickets import should_route_to_jira_ticket

    if should_route_to_jira_ticket(user_message, context):
        return None
    missing = detect_missing_context(user_message, context)
    if missing:
        return clarification_response(missing)
    return None


async def varys_work_request_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from tempa.agents.specialists import _extract_meet_url
    from tempa.orchestrator.routing import is_coding_work_request

    if _extract_meet_url(user_message):
        return None
    if not is_coding_work_request(user_message, context):
        return None

    from tempa.varys import harness
    from tempa.varys.vault_sync import append_session_log, ensure_vault_initialized

    ensure_vault_initialized()
    channel = str(context.get("channel") or "dashboard")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    db = harness.get_db()
    try:
        ticket_id = harness.create_ticket(
            db,
            title=user_message[:200],
            origin_channel=channel,
            origin_thread=thread_ts,
            payload={
                "message": user_message,
                **{k: v for k, v in context.items() if k.startswith("slack_")},
            },
        )
    finally:
        db.close()

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
    append_session_log(f"Work ticket created: {ticket_id} — {user_message[:120]}")
    return {
        "response": (
            f"Logged work ticket `{ticket_id}`. I'll draft a plan and wait for your approval "
            f"(reply *go* or approve in the dashboard when ready to implement)."
        ),
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


async def jira_direct_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from tempa.channels.jira.direct_reply import try_jira_direct_reply

    direct = await try_jira_direct_reply(user_message, context)
    if direct:
        return {
            "response": direct,
            "sources": [],
            "paused": False,
            "pending_actions": [],
            "artifacts": [],
        }
    return None


async def slack_direct_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from tempa.channels.slack.direct_reply import try_slack_direct_reply

    direct = await try_slack_direct_reply(user_message, context)
    if direct:
        return {
            "response": direct,
            "sources": [],
            "paused": False,
            "pending_actions": [],
            "artifacts": [],
        }
    return None


def register_all_hooks() -> None:
    from tempa.orchestrator.hooks import register_pre_hook

    register_pre_hook("go_signal", go_signal_hook)
    register_pre_hook("jira_ticket", jira_ticket_hook)
    register_pre_hook("clarification", clarification_hook)
    register_pre_hook("varys_work_request", varys_work_request_hook)
    register_pre_hook("jira_direct", jira_direct_hook)
    register_pre_hook("slack_direct", slack_direct_hook)
