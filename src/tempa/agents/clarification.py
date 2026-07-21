from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
_GITHUB_REPO_RE = re.compile(r"github\.com/[\w.\-]+/[\w.\-]+", re.I)
_GITHUB_OWNER_REPO_RE = re.compile(r"\b[\w.\-]+/[\w.\-]+\b")
_MEET_URL_RE = re.compile(r"https://meet\.google\.com/[a-z0-9\-]+", re.I)
_TIME_HINT_RE = re.compile(
    r"\b("
    r"\d{1,2}(:\d{2})?\s*(am|pm)|"
    r"today|tomorrow|tonight|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"next week|this week|"
    r"at \d|"
    r"\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r")\b",
    re.I,
)

CLARIFICATION_INSTRUCTION = (
    "If the user's request cannot be completed without missing details "
    "(recipient, time, repo URL, issue key, file path, etc.), ask one clear "
    "question stating exactly what you need. Never invent or assume missing facts. "
    "Never ask for credentials, passwords, tokens, or API keys. "
    "If they named a known product/app, shared a Jira issue link, or a GitHub PR/repo, "
    "use that context and investigate — do not ask for steps you can infer."
)


def clarification_response(
    question: str,
    *,
    context: dict[str, Any] | None = None,
    slot: str = "",
    hint: str = "",
    register_open: bool = False,
) -> dict[str, Any]:
    if register_open:
        from tempa.rag.procedural import _infer_slot_from_question, register_open_clarification

        register_open_clarification(
            question,
            slot=slot or _infer_slot_from_question(question),
            context=context,
            hint=hint,
        )
    return {
        "response": question,
        "sources": [],
        "paused": False,
        "pending_actions": [],
        "artifacts": [],
    }


def apply_durable_slot_fills(user_message: str, context: dict[str, Any]) -> None:
    """Fill missing slots from durable memory into context (mutates context)."""
    from tempa.rag.procedural import find_default_repo, find_person_email

    combined = _combined_text(user_message, context)
    if _wants_send_email(user_message) and not _has_email_address(combined) and not context.get(
        "known_recipient_email"
    ):
        hint = _name_hint_from_combined(combined)
        if hint:
            email = find_person_email(hint)
            if email:
                context["known_recipient_email"] = email
                context["known_recipient_name"] = hint

    if not _has_repo_target(combined) and not context.get("known_repo"):
        repo = find_default_repo()
        if repo:
            context["known_repo"] = repo


def _combined_text(user_message: str, context: dict[str, Any]) -> str:
    recent = context.get("recent_user_messages") or []
    if isinstance(recent, list):
        tail = " ".join(str(m) for m in recent[-6:])
        return f"{user_message} {tail}".strip()
    return user_message


def _has_email_address(text: str) -> bool:
    return bool(_EMAIL_RE.search(text))


def _wants_send_email(text: str) -> bool:
    lower = text.lower()
    if not any(k in lower for k in ("send", "compose", "write", "reply", "forward", "draft")):
        return False
    if any(k in lower for k in ("invite", "calendar", "calender", "meeting", "guest")):
        return False
    return any(k in lower for k in ("email", "mail", "gmail", "inbox")) or _has_email_address(text)


def _has_time_hint(text: str) -> bool:
    return bool(_TIME_HINT_RE.search(text))


def _has_repo_target(text: str) -> bool:
    if _GITHUB_REPO_RE.search(text):
        return True
    lower = text.lower()
    if "github.com" in lower:
        return True
    if "scan repo" in lower or "scan this repo" in lower:
        return _GITHUB_OWNER_REPO_RE.search(text) is not None
    return False


def _name_hint_from_combined(combined: str) -> str:
    match = re.search(r"\b(?:to|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", combined)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b(?:email|mail)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", combined)
    if match:
        return match.group(1).strip()
    return ""


def detect_missing_context(user_message: str, context: dict[str, Any] | None = None) -> str | None:
    """Return a clarifying question when required details are absent, else None."""
    text = (user_message or "").strip()
    if not text:
        return None

    # Mutate caller's context in place so durable slot fills stick for planners.
    ctx = context if isinstance(context, dict) else {}
    combined = _combined_text(text, ctx)
    lower = text.lower()

    try:
        from tempa.channels.jira.tickets import should_route_to_jira_ticket, ticket_feature_enabled

        if ticket_feature_enabled() and should_route_to_jira_ticket(text, ctx):
            return None
    except Exception:
        pass

    from tempa.agents.intent import extract_jira_issue_key, is_casual_greeting, wants_jira, wants_repo_qa
    from tempa.varys.manager import is_go_signal

    if is_go_signal(text) or is_casual_greeting(text):
        return None

    if _wants_send_email(text) and not _has_email_address(combined) and not ctx.get(
        "known_recipient_email"
    ):
        hint = _name_hint_from_combined(combined)
        try:
            from tempa.rag.procedural import find_person_email

            email = find_person_email(hint) if hint else None
        except Exception:
            email = None
        if email:
            ctx["known_recipient_email"] = email
            ctx["known_recipient_name"] = hint
        elif hint:
            return f"You mentioned {hint} — what's their email address?"
        else:
            return "Who should I send the email to? Please share the recipient's email address."

    from tempa.channels.calendar.events import wants_create_event, wants_send_calendar_invite

    if wants_create_event(text) or wants_send_calendar_invite(text):
        if not _has_time_hint(combined):
            return "What date and time should I schedule this for?"

    if (
        ("join" in lower and "meet" in lower)
        or lower.startswith("join ")
    ) and not _MEET_URL_RE.search(combined) and not ctx.get("meet_url"):
        return "Please share the Google Meet link you'd like me to join."

    scan_intent = wants_repo_qa(text) or (
        any(k in lower for k in ("scan repo", "scan this", "repo scan", "branch scan"))
        and any(k in lower for k in ("scan", "qa", "audit", "check"))
    )
    if scan_intent and not _has_repo_target(combined) and not ctx.get("known_repo"):
        try:
            from tempa.rag.procedural import find_default_repo

            repo = find_default_repo()
        except Exception:
            repo = None
        if repo:
            ctx["known_repo"] = repo
        else:
            return "Which repository should I scan? Share the GitHub URL or owner/repo name."

    if wants_jira(text) and not extract_jira_issue_key(text):
        if any(
            phrase in lower
            for phrase in (
                "status of",
                "details for",
                "show issue",
                "get issue",
                "look up issue",
                "tell me about",
            )
        ) and not any(k in lower for k in ("project", "list", "search", "jql", "backlog")):
            return "Which Jira issue key should I look up (e.g. ENG-123)?"

    pc_write_intent = any(k in lower for k in ("write file", "create file", "save to"))
    if pc_write_intent and not re.search(r"[/\\][\w.\-/]+|\.\w{1,6}\b", text):
        return "Which file path should I use? Please provide the full path or filename."

    slack_send = any(k in lower for k in ("message ", "dm ", "slack ", "messege")) and any(
        k in lower for k in ("send", "tell", "notify", "ping")
    )
    if slack_send and not re.search(r"<@[A-Z0-9]+>|#\w+|channel ", text, re.I):
        from tempa.channels.slack.recipients import extract_slack_recipient_name
        from tempa.core.cross_channel_conversation import last_assistant_text

        # "send this to Zeeshan" — recipient name + last reply is enough
        if extract_slack_recipient_name(text) and last_assistant_text(ctx):
            return None
        if not any(k in lower for k in ("team", "channel", "everyone")) and not extract_slack_recipient_name(
            text
        ):
            return "Who should I message on Slack — a person, channel, or thread?"

    return None
