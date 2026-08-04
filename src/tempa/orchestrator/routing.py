from __future__ import annotations

import re
from typing import Any

_GITHUB_REPO_RE = re.compile(r"github\.com/[\w.\-]+/[\w.\-]+", re.I)

# Teammate product-bug phrasing (Slack) that should hit Cursor, not QA lint scans.
_PRODUCT_INVESTIGATE_RE = re.compile(
    r"\b("
    r"figure out|go through the code|check if|why (?:is|are|does|did)|"
    r"not working|vanish(?:es|ing)?|wrong count|should be (?:higher|lower)|"
    r"investigate|root cause|what(?:'s| is) happening|trace|debug|"
    r"reproduce|repro|end.?to.?end|tdd"
    r")\b",
    re.I,
)


def _has_explicit_github_ref(text: str) -> bool:
    if _GITHUB_REPO_RE.search(text or ""):
        return True
    try:
        from tempa.qa.github.parse import has_explicit_github_ref

        return has_explicit_github_ref(text)
    except Exception:
        return False


def _has_coding_context(text: str) -> bool:
    lower = text.lower()
    if _has_explicit_github_ref(text):
        return True
    if any(k in lower for k in ("pull request", "pr #", " codebase", " in repo", " in the codebase")):
        return True
    if " repo" in lower or lower.startswith("repo ") or " repository" in lower:
        return True
    try:
        from tempa.qa.github.parse import resolve_repo_alias

        if resolve_repo_alias(text):
            return True
    except Exception:
        pass
    return False


def _looks_like_code_followup(text: str) -> bool:
    """Short thread follow-ups that inherit the repo from prior turns."""
    try:
        from tempa.channels.slack.cursor_pr import is_pr_comment_intent, is_write_intent

        if is_write_intent(text) or is_pr_comment_intent(text):
            return True
    except Exception:
        pass
    lower = (text or "").lower()
    return any(
        p in lower
        for p in (
            "fix it",
            "fix all",
            "fix them",
            "raise pr",
            "rase pr",
            "open pr",
            "create pr",
            "make a pr",
            "ship it",
            "do it",
            "address the",
            "resolve the",
            "comment on",
            "post comment",
            "post on github",
            "on github",
            "final comment",
            "leave a comment",
            "leave a review",
            "approve the pr",
            "approve pr",
        )
    )


def is_rumi_agent_request(user_message: str, context: dict[str, Any] | None = None) -> bool:
    """True when the message targets the vendored Rumi skills pack (any mode)."""
    _ = context
    from tempa.rumi.classify import classify_rumi

    return classify_rumi(user_message) is not None


def is_rumi_capability_ask(user_message: str, context: dict[str, Any] | None = None) -> bool:
    """True for inventory/capability asks — never meeting search / Cursor."""
    _ = context
    from tempa.rumi.classify import classify_rumi

    return classify_rumi(user_message) == "capability"


def is_coding_work_request(user_message: str, context: dict[str, Any] | None = None) -> bool:
    """True when the message is a Varys/coding task — not calendar/email/meet.

    Explicit GitHub refs (URL or owner/repo) always count as coding so Tempa
    can ack and Cursor can work the repo in the background. Short follow-ups
    like "raise PR and fix it all" inherit the repo from the Slack thread.
    """
    from tempa.agents.intent import wants_calendar, wants_gmail_full, wants_meeting_archive
    from tempa.agents.specialists import _extract_meet_url
    from tempa.varys.manager import is_work_request

    text = (user_message or "").strip()
    if not text:
        return False

    lower = text.lower()
    ctx = dict(context or {})

    if _extract_meet_url(text) or "meet.google.com" in lower:
        return False

    if wants_calendar(text) or wants_meeting_archive(text):
        return False

    # Rumi skills-pack asks are not product coding / PR jobs.
    if is_rumi_agent_request(text, ctx):
        return False

    # Coolify deploy/hosting is not a Cursor coding job.
    try:
        from tempa.channels.coolify.intent import wants_coolify_deploy

        if wants_coolify_deploy(text):
            return False
    except Exception:
        pass

    if any(k in lower for k in ("calendar", "inbox", "gmail", "meet.google.com", "standup minutes")):
        if "slack" not in lower and not _has_coding_context(text):
            return False

    # github.com/owner/repo (or owner/repo) → Cursor, not LLM clarify / QA steal.
    if _has_explicit_github_ref(text):
        return True

    # "rase pr and fix it all" in a thread that already named the repo.
    if _looks_like_code_followup(text):
        try:
            from tempa.channels.slack.cursor_threads import thread_coding_context_blob

            blob = thread_coding_context_blob(ctx)
            if blob and _has_coding_context(blob):
                return True
        except Exception:
            pass

    if is_work_request(text):
        if wants_gmail_full(text) and "slack" not in lower:
            if any(k in lower for k in ("inbox", "email", "gmail")) and not _has_coding_context(text):
                return False
        return True

    if _has_coding_context(text) and any(
        k in lower
        for k in (
            "fix",
            "implement",
            "refactor",
            "debug",
            "investigate",
            "build",
            "add ",
            "improve",
            "review",
            "analyze",
            "analyse",
            "look at",
            "how can we",
            "how do we",
        )
    ):
        return True

    # "In compliance tracker… check if the count / figure out vanishing" → Cursor job.
    if _has_coding_context(text) and _PRODUCT_INVESTIGATE_RE.search(text):
        return True

    return False


def should_use_claude_merge(user_message: str, context: dict[str, Any] | None = None) -> bool:
    """Decide whether orchestrator merge uses Claude (Varys) vs Groq.

    Coding work is owned by Cursor when configured — Claude merge is only for
    non-coding channel/tool planning in varys/hybrid modes.
    """
    from tempa.settings import get_settings
    from tempa.varys.manager import is_go_signal

    ctx = dict(context or {})
    if ctx.get("force_varys") or ctx.get("varys_dispatch"):
        return True

    if is_go_signal(user_message):
        return False

    coding = is_coding_work_request(user_message, ctx)
    if coding:
        try:
            from tempa.channels.slack.cursor_threads import cursor_owns_coding

            if cursor_owns_coding():
                return False
        except Exception:
            pass

    mode = (get_settings().tempa_coordinator or "langgraph").strip().lower()
    if mode == "langgraph":
        return False
    if mode == "varys":
        from tempa.qa.claude import claude_configured
        from tempa.varys.runner import claude_cli_available

        if not claude_cli_available() and not claude_configured():
            return False
        # Slack non-coding stays on Groq specialists; coding already returned above.
        if ctx.get("inbound_slack") and not coding:
            return False
        return True
    # hybrid: Claude only for coding when Cursor does not own it
    return coding
