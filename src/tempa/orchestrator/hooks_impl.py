from __future__ import annotations

from typing import Any


async def go_signal_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from tempa.agents.graph import _try_go_signal_approval

    return await _try_go_signal_approval(user_message, context)


async def qa_results_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Answer 'any bugs/errors/findings?' from the QA store — never ask clarifying questions."""
    from tempa.qa.config import qa_enabled
    from tempa.qa.github.parse import wants_qa_results
    from tempa.qa.results_reply import format_qa_results_reply, resolve_qa_repo_from_context

    if not qa_enabled() or not wants_qa_results(user_message):
        return None
    # Don't steal a fresh scan request that also mentions findings wording.
    lower = user_message.lower()
    if any(k in lower for k in ("scan", "review this", "do qa", "run qa", "check this", "audit")):
        if "github.com" in lower or "/" in user_message:
            return None

    repo = resolve_qa_repo_from_context(user_message, context)
    return {
        "response": format_qa_results_reply(repo),
        "sources": [],
        "paused": False,
        "pending_actions": [],
        "artifacts": [],
        "planned_steps": [],
    }


async def qa_scan_hook(user_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Deterministic route: a PR/repo link with review intent goes straight to the QA queue,
    bypassing the LLM planner (which otherwise asks clarifying questions)."""
    from tempa.qa.config import qa_enabled
    from tempa.qa.github.parse import parse_github_target, wants_github_qa

    if not qa_enabled():
        return None
    target = parse_github_target(user_message)
    if not target.repo:
        return None
    lower = user_message.lower()
    review_intent = wants_github_qa(user_message) or any(
        k in lower for k in ("review", "scan", "check", "test", "audit", "qa", "comment")
    )
    if not review_intent:
        return None

    from tempa.qa.scan_request import handle_github_scan_request

    from tempa.channels.slack.users import get_allowed_slack_user_ids, get_owner_slack_user_id
    from tempa.settings import get_settings

    channel = str(context.get("channel") or "coordinator")
    slack_user = str(context.get("slack_user_id") or "")
    requested_by = slack_user or str(
        context.get("whatsapp_number") or context.get("from_number") or channel
    )
    # Trust = explicit owner/allowlisted identities only (slack_allow_all is for chatting,
    # not for adding repos to the scan allowlist).
    owner_number = get_settings().whatsapp_owner_number.strip()
    trusted = bool(
        (slack_user and (slack_user == get_owner_slack_user_id() or slack_user in get_allowed_slack_user_ids()))
        or (owner_number and owner_number in requested_by)
        or channel == "dashboard"
    )
    try:
        result = handle_github_scan_request(
            user_message, source_channel=channel, requested_by=requested_by, trusted=trusted
        )
    except Exception as exc:
        return {
            "sources": [],
            "artifacts": [],
            "planned_steps": [],
            "response": f"Couldn't start the GitHub review for `{target.repo}`: {exc}",
            "paused": False,
            "pending_actions": [],
        }
    status = result.get("status")

    base = {"sources": [], "artifacts": [], "planned_steps": []}
    if status == "queued":
        if target.pr_number:
            response = (
                f"On it — queued a priority review for PR #{target.pr_number} on `{target.repo}`. "
                "I'll assign the PR if it has no assignee, then review the diff, "
                "run lint/tests/security checks, and comment the results on the PR."
            )
        elif target.branch:
            response = (
                f"On it — queued a full review of `{target.repo}` on branch `{target.branch}`. "
                "I'll clone the branch, run lint/tests/security checks, and report findings here."
            )
        else:
            response = (
                f"On it — queued a full review of `{target.repo}`. "
                "I'll run lint/tests/security checks and report findings here."
            )
        return {
            **base,
            "response": response,
            "paused": False,
            "pending_actions": [],
        }
    if status == "pending_approval":
        return {
            **base,
            "response": str(result.get("message") or "Repo needs approval before I can scan it."),
            "paused": True,
            "pending_actions": [
                {
                    "id": result.get("action_id"),
                    "type": "qa_repo_scan",
                    "preview": user_message[:200],
                }
            ],
        }
    if status in ("error", "disabled"):
        return {
            **base,
            "response": str(result.get("message") or "QA scan is unavailable right now."),
            "paused": False,
            "pending_actions": [],
        }
    return None


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
    from tempa.agents.clarification import (
        apply_durable_slot_fills,
        clarification_response,
        detect_missing_context,
    )
    from tempa.channels.jira.tickets import should_route_to_jira_ticket
    from tempa.rag.procedural import _infer_slot_from_question, resolve_open_clarification

    if should_route_to_jira_ticket(user_message, context):
        return None

    # Answer to a prior clarifying question → durable memory, then continue
    resolve_open_clarification(user_message, context)

    apply_durable_slot_fills(user_message, context)
    missing = detect_missing_context(user_message, context)
    if missing:
        hint = ""
        if "mentioned" in missing.lower():
            import re

            m = re.search(r"mentioned\s+(\w+)", missing, re.I)
            if m:
                hint = m.group(1)
        return clarification_response(
            missing,
            context=context,
            slot=_infer_slot_from_question(missing),
            hint=hint,
            register_open=True,
        )
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
    register_pre_hook("qa_results", qa_results_hook)
    register_pre_hook("qa_scan", qa_scan_hook)
    register_pre_hook("jira_ticket", jira_ticket_hook)
    register_pre_hook("clarification", clarification_hook)
    register_pre_hook("varys_work_request", varys_work_request_hook)
    register_pre_hook("jira_direct", jira_direct_hook)
    register_pre_hook("slack_direct", slack_direct_hook)
