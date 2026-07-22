from __future__ import annotations

import json
import logging
import re
from typing import Any

from tempa.core.cross_channel_conversation import format_conversation_lines
from tempa.core.events import event_bus

logger = logging.getLogger(__name__)

# Never ask the user for secrets — Tempa uses server-side GitHub/Slack/etc auth.
_SECRET_MISSING_RE = re.compile(
    r"\b(credential|credentials|password|passwd|secret|api[\s_-]?key|access[\s_-]?token|"
    r"auth(?:entication)?(?:\s+(?:token|key|credential))?|github\s+token|pat)\b",
    re.I,
)


def _sanitize_missing_info(items: list[Any] | None) -> list[str]:
    cleaned: list[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if not text or _SECRET_MISSING_RE.search(text):
            continue
        cleaned.append(text)
    return cleaned


def _heuristic_user_goal(user_message: str, context: dict[str, Any]) -> dict[str, Any]:
    from tempa.agents.intent import (
        wants_calendar_full,
        wants_gmail_full,
        wants_jira,
        wants_meeting_archive,
        wants_notion,
        wants_repo_qa,
    )

    lower = user_message.lower()
    suggested: list[str] = []
    if wants_gmail_full(user_message):
        suggested.append("gmail")
    if wants_calendar_full(user_message):
        suggested.append("calendar")
    if wants_meeting_archive(user_message) or "meet.google.com" in lower:
        suggested.append("meet")
    if wants_repo_qa(user_message):
        suggested.append("qa")
    if wants_jira(user_message):
        suggested.append("plugin")
    if wants_notion(user_message):
        suggested.append("plugin")
    if any(k in lower for k in ("whatsapp", "slack", "message", "notify")):
        suggested.append("channel")
    if any(k in lower for k in ("shell", "file", "vscode", "open app", "pc ")):
        suggested.append("pc")

    missing: list[str] = []
    if any(k in lower for k in ("send", "reply", "email", "mail")) and "@" not in user_message:
        if "to " not in lower and "recipient" not in lower:
            missing.append("who to email or message")

    constraints: list[str] = []
    channel = str(context.get("channel") or "")
    if channel:
        constraints.append(f"reply on {channel}")

    return {
        "goal": user_message.strip(),
        "constraints": constraints,
        "missing_info": _sanitize_missing_info(missing),
        "suggested_agents": list(dict.fromkeys(suggested)),
    }


async def understand_user_goal(user_message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Stage 1: derive structured user_goal from message + history."""
    from tempa.agents.intent import is_casual_greeting

    if is_casual_greeting(user_message):
        goal = _heuristic_user_goal(user_message, context)
        await event_bus.publish_json("orchestrator", "activity", f"understand:{goal['goal'][:120]}")
        return goal

    goal = _heuristic_user_goal(user_message, context)
    if len(user_message) < 120 and not context.get("conversation_messages"):
        await event_bus.publish_json(
            "orchestrator", "activity", f"understand:{goal['goal'][:120]}"
        )
        return goal

    from tempa.agents.config import model_category_for_agent
    from tempa.router.groq_router import get_router

    conv = format_conversation_lines(context.get("conversation_messages") or [], limit=10)
    router = get_router()
    prompt = (
        "Analyze the user request. Return JSON only:\n"
        '{"goal": "...", "constraints": [], "missing_info": [], "suggested_agents": []}\n'
        "suggested_agents: subset of meet, channel, calendar, gmail, rag, pc, plugin, qa\n"
        "missing_info: list clarifications needed before acting (empty if none). "
        "Never ask for credentials, passwords, tokens, API keys, or auth secrets — "
        "Tempa already has server-side GitHub/Slack/Google access. "
        "A public GitHub URL plus review/scan/test intent is complete; missing_info must be []. "
        "If the user says send/forward 'this'/'that'/'the above' and the conversation already "
        "has an assistant reply, missing_info must be [] — reuse that reply as the message body.\n"
        f"Conversation:\n" + "\n".join(conv) + "\n"
        f"User message: {user_message}"
    )
    try:
        response = router.chat_completion(
            category=model_category_for_agent("coordinator", "reasoning"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        if isinstance(data, dict) and data.get("goal"):
            goal = {
                "goal": str(data.get("goal") or user_message).strip(),
                "constraints": list(data.get("constraints") or goal.get("constraints") or []),
                "missing_info": _sanitize_missing_info(list(data.get("missing_info") or [])),
                "suggested_agents": list(
                    data.get("suggested_agents") or goal.get("suggested_agents") or []
                ),
            }
    except Exception as exc:
        logger.warning("understand_user_goal LLM failed: %s", exc)

    goal["missing_info"] = _sanitize_missing_info(goal.get("missing_info"))
    # Public GitHub URL + review intent is actionable — never stall for invented clarifications.
    try:
        from tempa.qa.github.parse import parse_github_target, wants_github_qa, wants_qa_results

        if wants_qa_results(user_message):
            goal["missing_info"] = []
        elif wants_github_qa(user_message) and parse_github_target(user_message).repo:
            goal["missing_info"] = []
        elif parse_github_target(user_message).repo:
            # Product alias (e.g. "compliance tracker") or bare owner/repo — investigate, don't quiz.
            goal["missing_info"] = []
    except Exception:
        pass

    # Existing Jira issue key / browse URL — look it up, don't invent create/assignee questions.
    try:
        from tempa.agents.intent import extract_jira_issue_key

        if extract_jira_issue_key(user_message):
            goal["missing_info"] = []
    except Exception:
        pass

    # "send this to X" — body = last assistant reply; don't ask for text/channel again.
    try:
        from tempa.channels.slack.recipients import (
            extract_slack_recipient_name,
            wants_slack_send_intent,
        )
        from tempa.core.cross_channel_conversation import last_assistant_text

        lower = user_message.lower()
        if wants_slack_send_intent(user_message) and last_assistant_text(context):
            if extract_slack_recipient_name(user_message) or any(
                k in lower for k in ("this", "that", "above", "summary", "report", "findings")
            ):
                goal["missing_info"] = []
    except Exception:
        pass
    await event_bus.publish_json("orchestrator", "activity", f"understand:{goal['goal'][:120]}")
    return goal
