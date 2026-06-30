from __future__ import annotations

import re
from typing import Any

_GITHUB_REPO_RE = re.compile(r"github\.com/[\w.\-]+/[\w.\-]+", re.I)


def _has_coding_context(text: str) -> bool:
    lower = text.lower()
    if _GITHUB_REPO_RE.search(text):
        return True
    if any(k in lower for k in ("pull request", "pr #", " codebase", " in repo", " in the codebase")):
        return True
    if " repo" in lower or lower.startswith("repo ") or " repository" in lower:
        return True
    return False


def is_coding_work_request(user_message: str, context: dict[str, Any] | None = None) -> bool:
    """True when the message is a Varys/coding task — not calendar/email/meet."""
    from tempa.agents.intent import wants_calendar, wants_gmail_full, wants_meeting_archive
    from tempa.agents.specialists import _extract_meet_url
    from tempa.varys.manager import is_work_request

    text = (user_message or "").strip()
    if not text:
        return False

    lower = text.lower()

    if _extract_meet_url(text) or "meet.google.com" in lower:
        return False

    if wants_calendar(text) or wants_meeting_archive(text):
        return False

    if any(k in lower for k in ("calendar", "inbox", "gmail", "meet.google.com", "standup minutes")):
        if "slack" not in lower and not _has_coding_context(text):
            return False

    if is_work_request(text):
        if wants_gmail_full(text) and "slack" not in lower:
            if any(k in lower for k in ("inbox", "email", "gmail")) and not _has_coding_context(text):
                return False
        return True

    if _has_coding_context(text) and any(
        k in lower for k in ("fix", "implement", "refactor", "debug", "investigate", "build", "add ")
    ):
        return True

    return False


def should_use_claude_merge(user_message: str, context: dict[str, Any] | None = None) -> bool:
    """Decide whether orchestrator merge uses Claude (Varys) vs Groq."""
    from tempa.settings import get_settings
    from tempa.varys.manager import is_go_signal

    ctx = dict(context or {})
    if ctx.get("force_varys") or ctx.get("varys_dispatch"):
        return True

    if is_go_signal(user_message):
        return False

    mode = (get_settings().tempa_coordinator or "langgraph").strip().lower()
    if mode == "varys":
        from tempa.qa.claude import claude_configured
        from tempa.varys.runner import claude_cli_available

        if not claude_cli_available() and not claude_configured():
            return False
        if ctx.get("inbound_slack") and not is_coding_work_request(user_message, ctx):
            return False
        return True
    if mode == "langgraph":
        return False

    return is_coding_work_request(user_message, ctx)
