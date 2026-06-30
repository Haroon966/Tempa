from __future__ import annotations

import re

# Slack-native tokens we must not alter during Markdown conversion.
_SLACK_TOKEN_RE = re.compile(
    r"(<@[A-Z0-9]+>|<#[A-Z0-9]+(?:\|[^>]+)?>|<![^>]+>|<https?://[^>|]+(?:\|[^>]+)?>)"
)
_PLACEHOLDER = "\x00SLACK{}\x00"

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_BOLD_UNDER_RE = re.compile(r"__(.+?)__")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_BARE_URL_RE = re.compile(r"(?<!<)(https?://[^\s<>|]+)")


def _protect_slack_tokens(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def repl(match: re.Match[str]) -> str:
        tokens.append(match.group(0))
        return _PLACEHOLDER.format(len(tokens) - 1)

    return _SLACK_TOKEN_RE.sub(repl, text), tokens


def _restore_slack_tokens(text: str, tokens: list[str]) -> str:
    for i, token in enumerate(tokens):
        text = text.replace(_PLACEHOLDER.format(i), token)
    return text


def format_for_slack(text: str) -> str:
    """Convert common Markdown to Slack mrkdwn for chat_postMessage."""
    if not text or not text.strip():
        return text

    protected, tokens = _protect_slack_tokens(text)

    protected = _MD_LINK_RE.sub(r"<\2|\1>", protected)
    protected = _MD_BOLD_RE.sub(r"*\1*", protected)
    protected = _MD_BOLD_UNDER_RE.sub(r"*\1*", protected)
    protected = _MD_HEADING_RE.sub(r"*\1*", protected)

    def _strip_fence_lang(match: re.Match[str]) -> str:
        body = match.group(2).rstrip("\n")
        return f"```\n{body}\n```"

    protected = _FENCE_RE.sub(_strip_fence_lang, protected)

    protected = _restore_slack_tokens(protected, tokens)

    # Wrap bare URLs (not already in Slack link syntax).
    protected, tokens2 = _protect_slack_tokens(protected)
    protected = _BARE_URL_RE.sub(r"<\1>", protected)
    protected = _restore_slack_tokens(protected, tokens2)

    return protected


def prepare_slack_reply(text: str) -> str:
    return format_for_slack(text).strip()
