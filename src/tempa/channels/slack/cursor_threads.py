"""Route pinned Slack threads through Tempa Cursor jobs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from tempa.settings import get_settings

log = logging.getLogger(__name__)

_cache_mtime: float | None = None
_cache_rows: list[dict[str, Any]] = []


def _ts_equal(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def load_cursor_threads() -> list[dict[str, Any]]:
    """Load pins with mtime-aware reload (no process restart needed)."""
    global _cache_mtime, _cache_rows
    path = get_settings().config_dir / "cursor_threads.yaml"
    if not path.exists():
        _cache_mtime = None
        _cache_rows = []
        return []
    mtime = path.stat().st_mtime
    if _cache_mtime is not None and mtime == _cache_mtime:
        return list(_cache_rows)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rows = data.get("threads") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        _cache_mtime = mtime
        _cache_rows = []
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        channel_id = str(row.get("channel_id") or "").strip()
        thread_ts = str(row.get("thread_ts") or "").strip()
        if not channel_id or not thread_ts:
            continue
        required = row.get("required_checks")
        if not isinstance(required, list):
            required = ["backend-ci", "frontend-ci", "e2e"]
        out.append(
            {
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "repo": str(row.get("repo") or "").strip(),
                "starting_ref": str(row.get("starting_ref") or "").strip() or None,
                "local_cwd": str(row.get("local_cwd") or "").strip(),
                "label": str(row.get("label") or "").strip(),
                "base_ref": str(row.get("base_ref") or "main").strip() or "main",
                "jira_key": str(row.get("jira_key") or "").strip() or None,
                "required_checks": [str(x).strip() for x in required if str(x).strip()],
            }
        )
    _cache_mtime = mtime
    _cache_rows = out
    log.info("slack.cursor_thread config loaded %s threads", len(out))
    return list(out)


def match_cursor_thread(channel_id: str, thread_ts: str) -> dict[str, Any] | None:
    ch = str(channel_id or "").strip()
    ts = str(thread_ts or "").strip()
    if not ch or not ts:
        return None
    for row in load_cursor_threads():
        if row["channel_id"] == ch and _ts_equal(row["thread_ts"], ts):
            return row
    return None


def is_cursor_thread(channel_id: str, thread_ts: str) -> bool:
    return match_cursor_thread(channel_id, thread_ts) is not None


def _resolve_user_label(client: Any, user_id: str, cache: dict[str, str]) -> str:
    uid = str(user_id or "").strip()
    if not uid:
        return "?"
    if uid in cache:
        return cache[uid]
    try:
        from tempa.channels.slack.client import user_display_name

        info = client.users_info(user=uid)
        user = info.get("user") if isinstance(info, dict) else None
        label = user_display_name(user) if isinstance(user, dict) else uid
    except Exception:
        label = uid
    cache[uid] = label
    return label


def _thread_transcript(context: dict[str, Any], *, limit: int = 24) -> str:
    channel_id = str(context.get("slack_channel_id") or context.get("channel_id") or "")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    if not channel_id or not thread_ts:
        return ""
    try:
        from tempa.channels.slack.client import load_slack_client

        client = load_slack_client()
        response = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=min(max(limit, 1), 50),
        )
        messages = list(response.get("messages") or [])[-limit:]
        name_cache: dict[str, str] = {}
        lines: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            uid = str(msg.get("user") or "")
            who = _resolve_user_label(client, uid, name_cache) if uid else str(msg.get("bot_id") or "bot")
            text = str(msg.get("text") or "").strip()
            if not text:
                continue
            if len(text) > 600:
                text = text[:597] + "..."
            lines.append(f"{who}: {text}")
        body = "\n".join(lines)
        if len(body) > 8000:
            body = body[-8000:]
        return body
    except Exception:
        log.exception("Failed to fetch Slack thread for Cursor prompt")
        return ""


async def handle_cursor_thread_message(
    text: str,
    context: dict[str, Any],
) -> str | None:
    """Enqueue a durable Tempa Cursor job for a pinned thread.

    Returns a short ack string for the Slack handler (or an error). The real
    answer is posted asynchronously by the Cursor worker.
    """
    from tempa.channels.slack import cursor_progress as prog
    from tempa.channels.slack.cursor_worker import enqueue_from_slack
    from tempa.qa.cursor import cursor_configured

    channel_id = str(context.get("slack_channel_id") or context.get("channel_id") or "")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    cfg = match_cursor_thread(channel_id, thread_ts)
    if not cfg:
        return None
    if not cursor_configured():
        return (
            "This thread is set to answer via Cursor, but `CURSOR_API_KEY` is not "
            "configured on Tempa."
        )

    local_cwd = str(cfg.get("local_cwd") or "").strip()
    if local_cwd and not Path(local_cwd).is_dir():
        return (
            "Tempa Cursor thread misconfigured: local repo path is not available "
            f"(`{local_cwd}`). Check the Tempa Docker volume mount."
        )

    result = enqueue_from_slack(text=text, context=context, cfg=cfg)
    if result.get("error"):
        return f"_Tempa hit a problem: {result['error']}_"
    if result.get("queued_position"):
        return prog.msg_queued(int(result["queued_position"]))
    return prog.msg_working()
