from __future__ import annotations

from typing import Any

PRIVATE_RAG_TOOLS = frozenset({"gmail", "whatsapp", "calendar", "meet"})
PRIVATE_AGENTS = frozenset({"gmail", "calendar", "meet", "pc"})
GUEST_RAG_TOOLS = frozenset({"slack"})


def is_slack_guest(context: dict[str, Any] | None) -> bool:
    ctx = context or {}
    return ctx.get("channel") == "slack" and not ctx.get("slack_privileged")


def include_private_grounding(context: dict[str, Any] | None) -> bool:
    return not is_slack_guest(context)


def allowed_agents(context: dict[str, Any] | None) -> frozenset[str] | None:
    if is_slack_guest(context):
        from tempa.orchestrator.config import load_orchestrator_config

        return load_orchestrator_config().guest_slack_workers
    return None


def allowed_rag_tools(context: dict[str, Any] | None) -> frozenset[str] | None:
    if is_slack_guest(context):
        return GUEST_RAG_TOOLS
    return None


def filter_subtasks(subtasks: list[dict[str, Any]], context: dict[str, Any] | None) -> list[dict[str, Any]]:
    allowed = allowed_agents(context)
    if allowed is None:
        return subtasks
    return [t for t in subtasks if str(t.get("agent") or "") in allowed]


def filter_rag_results(
    results: list[dict[str, Any]],
    context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    allowed = allowed_rag_tools(context)
    if allowed is None:
        return results
    filtered: list[dict[str, Any]] = []
    for row in results:
        tool = str((row.get("metadata") or {}).get("tool") or "")
        if tool in allowed:
            filtered.append(row)
    return filtered


def guest_merge_instruction(context: dict[str, Any] | None) -> str:
    if not is_slack_guest(context):
        return ""
    return (
        "You are replying to a Slack guest user. Do NOT share email, WhatsApp, calendar, "
        "or meeting information. If they ask about those integrations, briefly say they "
        "are not available on Slack yet. Keep replies friendly and limited to general help.\n"
    )
