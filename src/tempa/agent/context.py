"""Build prompt context: full thread, durable memory, attachments."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_THREAD_CHARS = 24_000
_MAX_MEMORY_ITEMS = 40


def _user_tag(user_id: str) -> str:
    uid = (user_id or "").strip()
    return f"user:{uid}" if uid else ""


def format_memory_block(*, user_id: str = "") -> str:
    """Compact durable prefs (per-user tags) + team facts for the agent prompt."""
    from tempa.rag.procedural import list_durable, list_preferences

    lines: list[str] = []
    utag = _user_tag(user_id)

    prefs = list_preferences()
    user_prefs: list[str] = []
    team_prefs: list[str] = []
    for p in prefs:
        text = str(p.get("text") or p.get("rule") or "").strip()
        if not text:
            continue
        tags = [str(t) for t in (p.get("tags") or [])]
        if utag and utag in tags:
            user_prefs.append(text)
        elif not any(t.startswith("user:") for t in tags):
            team_prefs.append(text)

    if user_prefs:
        lines.append("User preferences:")
        for t in user_prefs[:_MAX_MEMORY_ITEMS]:
            lines.append(f"- {t}")
    if team_prefs:
        lines.append("Team / shared preferences:")
        for t in team_prefs[:_MAX_MEMORY_ITEMS]:
            lines.append(f"- {t}")

    durable = list_durable(kinds=["fact", "person", "project", "decision"])
    facts: list[str] = []
    for item in durable:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kind = str(item.get("kind") or "fact")
        facts.append(f"[{kind}] {text}")
    if facts:
        lines.append("Team facts / projects / people / decisions:")
        for t in facts[:_MAX_MEMORY_ITEMS]:
            lines.append(f"- {t}")

    if not lines:
        return "(no durable memory yet)"
    return "\n".join(lines)


def fetch_slack_thread_transcript(
    *,
    channel_id: str,
    thread_ts: str,
    limit: int = 200,
) -> str:
    """Full Slack context: channel thread replies, or recent DM history."""
    from tempa.channels.slack.client import (
        iter_conversation_messages,
        list_users,
        load_slack_client,
        user_display_name,
    )

    client = load_slack_client()
    if client is None:
        return ""
    names: dict[str, str] = {}
    try:
        for u in list_users(client, limit=2000):
            uid = str(u.get("id") or "")
            if uid:
                names[uid] = user_display_name(u)
    except Exception:
        logger.debug("slack user list failed", exc_info=True)

    def _append_msg(msg: dict[str, Any], out: list[str]) -> None:
        uid = str(msg.get("user") or msg.get("bot_id") or "unknown")
        who = names.get(uid) or ("Tempa" if msg.get("bot_id") else uid)
        text = str(msg.get("text") or "").strip()
        if text:
            out.append(f"{who}: {text}")
        for f in msg.get("files") or []:
            name = str(f.get("name") or f.get("title") or "file")
            url = str(f.get("url_private") or f.get("permalink") or "").strip()
            extra = f" {url}" if url else ""
            out.append(f"{who}: [attachment: {name}]{extra}")

    lines: list[str] = []
    try:
        if str(channel_id).startswith("D"):
            # DMs: load recent IM history (not a single-message "thread").
            collected: list[dict[str, Any]] = []
            for msg in iter_conversation_messages(client, channel_id, limit=min(limit, 100)):
                collected.append(msg)
            for msg in reversed(collected):
                _append_msg(msg, lines)
        else:
            fetched = 0
            cursor = None
            while fetched < limit:
                page = min(200, limit - fetched)
                kwargs: dict[str, Any] = {
                    "channel": channel_id,
                    "ts": thread_ts,
                    "limit": page,
                }
                if cursor:
                    kwargs["cursor"] = cursor
                response = client.conversations_replies(**kwargs)
                for msg in response.get("messages") or []:
                    _append_msg(msg, lines)
                    fetched += 1
                    if fetched >= limit:
                        break
                cursor = (response.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break
    except Exception:
        logger.warning("failed to load Slack thread %s/%s", channel_id, thread_ts, exc_info=True)
        return ""

    blob = "\n".join(lines)
    if len(blob) > _MAX_THREAD_CHARS:
        blob = "…(earlier messages truncated)…\n" + blob[-_MAX_THREAD_CHARS:]
    return blob


def fetch_whatsapp_transcript(*, chat_id: str, limit: int = 80) -> str:
    """Recent WhatsApp turns for this chat from conversation store."""
    _ = chat_id  # store is currently global-owner history
    try:
        from tempa.channels.whatsapp.conversation import get_conversation_thread

        turns = get_conversation_thread(limit=limit, include_assistant=True)
    except Exception:
        logger.debug("whatsapp transcript unavailable", exc_info=True)
        return ""
    lines: list[str] = []
    for t in turns or []:
        if not isinstance(t, dict):
            continue
        role = str(t.get("role") or "user")
        who = "Tempa" if role == "assistant" else str(t.get("from_number") or "user")
        text = str(t.get("text") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    blob = "\n".join(lines)
    if len(blob) > _MAX_THREAD_CHARS:
        blob = "…(earlier messages truncated)…\n" + blob[-_MAX_THREAD_CHARS:]
    return blob


def prior_job_artifacts(*, channel_id: str, thread_ts: str) -> str:
    try:
        from tempa.channels.slack import cursor_jobs as jobs

        rows = jobs.find_jobs_for_thread(channel_id=channel_id, thread_ts=thread_ts, limit=10)
    except Exception:
        return ""
    parts: list[str] = []
    for row in rows or []:
        status = str(row.get("status") or "")
        ask = str(row.get("ask") or "")[:200]
        pr = str(row.get("pr_url") or "").strip()
        result = str(row.get("result_summary") or row.get("result") or "")[:500]
        line = f"- [{status}] {ask}"
        if pr:
            line += f" PR={pr}"
        if result:
            line += f" → {result}"
        parts.append(line)
    return "\n".join(parts)


def build_turn_prompt(
    *,
    user_message: str,
    channel: str,
    thread_id: str,
    user_id: str = "",
    channel_kind: str = "slack",
    extra_context: dict[str, Any] | None = None,
) -> str:
    memory = format_memory_block(user_id=user_id)
    if channel_kind == "whatsapp":
        thread = fetch_whatsapp_transcript(chat_id=thread_id or user_id)
        artifacts = ""
    else:
        thread = fetch_slack_thread_transcript(channel_id=channel, thread_ts=thread_id)
        artifacts = prior_job_artifacts(channel_id=channel, thread_ts=thread_id)

    parts = [
        "## Durable memory (user + team)",
        memory,
        "",
        "## Full thread so far",
        thread or "(empty thread — this is the first message)",
    ]
    if artifacts:
        parts.extend(["", "## Prior Tempa job artifacts in this thread", artifacts])
    try:
        from tempa.rumi.classify import classify_rumi

        if classify_rumi(user_message) == "agent":
            from tempa.channels.slack.cursor_threads import rumi_agent_job_cfg
            from tempa.channels.slack.rumi_pack import load_rumi_pack_context

            rumi_cwd = str(
                (extra_context or {}).get("local_cwd")
                or rumi_agent_job_cfg().get("local_cwd")
                or "/repos/rumixtempa"
            )
            pack = load_rumi_pack_context(rumi_cwd)
            if pack:
                parts.extend(["", "## Rumi skills pack (follow these skill files)", pack[:12000]])
    except Exception:
        logger.debug("rumi pack inject failed", exc_info=True)
    if extra_context:
        meet = extra_context.get("meet_url")
        if meet:
            parts.extend(["", f"Detected Meet URL: {meet}"])
        repo = extra_context.get("repo") or extra_context.get("local_cwd")
        if repo:
            parts.extend(["", f"Resolved coding workspace hint: {repo}"])
    parts.extend(
        [
            "",
            "## Latest user message",
            user_message.strip(),
            "",
            "Respond as Tempa. Use tools for Meet/calendar/mail/deploy/Jira/memory/code. "
            "Confirm before sending email or deploying. Prefer short clear updates.",
        ]
    )
    return "\n".join(parts)
