"""Route Slack coding work through Tempa Cursor jobs.

Pins (`threads`) override per-thread CI/Jira. Unpinned coding asks resolve a
repo from `repos` in cursor_threads.yaml (github URL, alias, or sole default).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from tempa.settings import get_settings

log = logging.getLogger(__name__)

_GITHUB_REPO_RE = re.compile(
    r"(?:github\.com/|git@github\.com:)([\w.\-]+)/([\w.\-]+?)(?:\.git)?(?=[/#?\s]|$)",
    re.I,
)

_cache_mtime: float | None = None
_cache_threads: list[dict[str, Any]] = []
_cache_repos: list[dict[str, Any]] = []


def _ts_equal(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def _normalize_repo_row(row: dict[str, Any]) -> dict[str, Any] | None:
    local_cwd = str(row.get("local_cwd") or "").strip()
    repo = str(row.get("repo") or "").strip()
    if not local_cwd and not repo:
        return None
    required = row.get("required_checks")
    if not isinstance(required, list):
        required = []
    aliases_raw = row.get("aliases")
    aliases: list[str] = []
    if isinstance(aliases_raw, list):
        aliases = [str(a).strip().lower() for a in aliases_raw if str(a).strip()]
    rid = str(row.get("id") or "").strip()
    if rid and rid.lower() not in aliases:
        aliases.append(rid.lower())
    if local_cwd:
        base = Path(local_cwd).name.lower()
        if base and base not in aliases:
            aliases.append(base)
    if repo:
        slug = repo.lower().removesuffix(".git")
        if slug not in aliases:
            aliases.append(slug)
        short = slug.rsplit("/", 1)[-1]
        if short and short not in aliases:
            aliases.append(short)
    return {
        "id": rid or (Path(local_cwd).name if local_cwd else repo),
        "repo": repo,
        "starting_ref": str(row.get("starting_ref") or "").strip() or None,
        "local_cwd": local_cwd,
        "label": str(row.get("label") or "").strip(),
        "base_ref": str(row.get("base_ref") or "main").strip() or "main",
        "jira_key": str(row.get("jira_key") or "").strip() or None,
        "required_checks": [str(x).strip() for x in required if str(x).strip()],
        "aliases": aliases,
    }


def _normalize_thread_row(row: dict[str, Any]) -> dict[str, Any] | None:
    channel_id = str(row.get("channel_id") or "").strip()
    thread_ts = str(row.get("thread_ts") or "").strip()
    if not channel_id or not thread_ts:
        return None
    base = _normalize_repo_row(row) or {
        "id": "",
        "repo": "",
        "starting_ref": None,
        "local_cwd": "",
        "label": "",
        "base_ref": "main",
        "jira_key": None,
        "required_checks": [],
        "aliases": [],
    }
    return {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "repo": base["repo"],
        "starting_ref": base["starting_ref"],
        "local_cwd": base["local_cwd"],
        "label": base["label"],
        "base_ref": base["base_ref"],
        "jira_key": base["jira_key"],
        "required_checks": base["required_checks"],
    }


def _reload_config() -> None:
    global _cache_mtime, _cache_threads, _cache_repos
    path = get_settings().config_dir / "cursor_threads.yaml"
    if not path.exists():
        _cache_mtime = None
        _cache_threads = []
        _cache_repos = []
        return
    mtime = path.stat().st_mtime
    if _cache_mtime is not None and mtime == _cache_mtime:
        return
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    threads_out: list[dict[str, Any]] = []
    for row in data.get("threads") or []:
        if isinstance(row, dict):
            norm = _normalize_thread_row(row)
            if norm:
                threads_out.append(norm)
    repos_out: list[dict[str, Any]] = []
    for row in data.get("repos") or []:
        if isinstance(row, dict):
            norm = _normalize_repo_row(row)
            if norm:
                repos_out.append(norm)
    _cache_mtime = mtime
    _cache_threads = threads_out
    _cache_repos = repos_out
    log.info(
        "slack.cursor_thread config loaded %s threads, %s repos",
        len(threads_out),
        len(repos_out),
    )


def load_cursor_threads() -> list[dict[str, Any]]:
    """Load pins with mtime-aware reload (no process restart needed)."""
    _reload_config()
    return list(_cache_threads)


def load_cursor_repos() -> list[dict[str, Any]]:
    """Load repo mounts for unpinned coding asks."""
    _reload_config()
    return list(_cache_repos)


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


def cursor_owns_coding() -> bool:
    """True when Cursor API is configured — mounts optional (cloud can use a GitHub URL)."""
    from tempa.qa.cursor import cursor_configured

    return cursor_configured()


def _github_slug_from_text(text: str) -> str | None:
    m = _GITHUB_REPO_RE.search(text or "")
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"


def _cloud_cfg_from_github(text: str) -> dict[str, Any] | None:
    """Ephemeral Cursor cloud target when the repo is not under repos: mounts."""
    slug = _github_slug_from_text(text or "")
    if not slug:
        try:
            from tempa.qa.github.parse import has_explicit_github_ref, parse_github_target

            if has_explicit_github_ref(text or ""):
                target = parse_github_target(text or "")
                slug = str(target.repo or "").strip() or None
        except Exception:
            slug = None
    if not slug or slug.count("/") != 1:
        return None
    from tempa.qa.cursor import resolve_cloud_starting_ref

    start = resolve_cloud_starting_ref(slug, None)
    return {
        "id": slug,
        "repo": slug,
        "starting_ref": start,
        "local_cwd": "",
        "label": slug,
        "base_ref": start,
        "jira_key": None,
        "required_checks": [],
        "aliases": [slug.lower(), slug.rsplit("/", 1)[-1].lower()],
    }


def _alias_in_text(alias: str, lower: str) -> bool:
    """Match repo aliases without false hits like alias `ct` inside `project`."""
    alias = (alias or "").strip().lower()
    if not alias or not lower:
        return False
    if " " in alias or "/" in alias:
        return alias in lower
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])", lower))


def match_cursor_repo(text: str, *, allow_sole_default: bool = True) -> dict[str, Any] | None:
    """Resolve a configured repo from message text (URL, alias, sole default, or cloud GitHub)."""
    repos = load_cursor_repos()
    lower = (text or "").lower()
    slug = _github_slug_from_text(text or "")

    # Explicit github.com/owner/repo always wins — never let alias `ct` steal "…project".
    if slug:
        slug_l = slug.lower()
        for row in repos:
            repo = str(row.get("repo") or "").lower()
            if repo == slug_l or slug_l in [a.lower() for a in (row.get("aliases") or [])]:
                return dict(row)
            if Path(str(row.get("local_cwd") or "")).name.lower() == slug_l.rsplit("/", 1)[-1]:
                return dict(row)
        cloud = _cloud_cfg_from_github(text)
        if cloud:
            return cloud

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in repos:
        for alias in row.get("aliases") or []:
            if _alias_in_text(str(alias), lower):
                scored.append((len(str(alias)), row))
                break
    if scored:
        scored.sort(key=lambda x: -x[0])
        return dict(scored[0][1])

    if not slug:
        cloud = _cloud_cfg_from_github(text)
        if cloud:
            return cloud

    if allow_sole_default and len(repos) == 1:
        return dict(repos[0])
    return None


def thread_coding_context_blob(context: dict[str, Any] | None = None) -> str:
    """Prior Slack turns for this thread — used to inherit repo on short follow-ups."""
    ctx = dict(context or {})
    channel_id = str(ctx.get("slack_channel_id") or ctx.get("channel_id") or "")
    thread_ts = str(ctx.get("slack_thread_ts") or ctx.get("thread_ts") or "")
    conv_key = str(ctx.get("slack_conversation_key") or "").strip()
    if not conv_key:
        is_dm = bool(ctx.get("slack_is_dm")) or str(channel_id).startswith("D")
        if is_dm and channel_id:
            conv_key = channel_id
        else:
            conv_key = thread_ts
    parts: list[str] = []
    if channel_id and (conv_key or thread_ts):
        try:
            from tempa.channels.slack.conversation import list_thread_messages

            for row in list_thread_messages(
                channel_id=channel_id,
                thread_ts=thread_ts,
                conversation_key=conv_key,
                limit=40,
            ):
                text = str(row.get("text") or "").strip()
                if text:
                    parts.append(text)
        except Exception:
            pass
        if len(parts) < 2:
            try:
                from tempa.channels.slack.conversation import get_recent_messages

                for row in get_recent_messages(
                    limit=40, channel_id=channel_id, conversation_key=conv_key or thread_ts
                ):
                    text = str(row.get("text") or "").strip()
                    if text:
                        parts.append(text)
            except Exception:
                pass
        if len(parts) < 2:
            live = _thread_transcript(ctx, limit=24)
            if live:
                parts.append(live)
    for key in ("recent_user_messages", "recent_conversation", "conversation_messages"):
        for item in ctx.get(key) or []:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    parts.append(text)
    return "\n".join(parts)


def coerce_cloud_when_mount_missing(
    cfg: dict[str, Any],
    text: str = "",
) -> dict[str, Any]:
    """Configured mount that isn't on disk → Cursor cloud (repo from cfg or message).

    Live failure: CT is in cursor_threads.yaml but /repos/compliancetracker isn't
    mounted in the container; explicit github.com asks must not die on Docker mount
    copy — cloud can still investigate/fix.
    """
    local_cwd = str(cfg.get("local_cwd") or "").strip()
    if not local_cwd or Path(local_cwd).is_dir():
        return cfg
    repo = str(cfg.get("repo") or "").strip() or (_github_slug_from_text(text) or "")
    if not repo:
        return cfg
    out = dict(cfg)
    out["local_cwd"] = ""
    out["repo"] = repo
    log.warning(
        "cursor mount missing at %s — falling back to Cursor cloud for %s",
        local_cwd,
        repo,
    )
    return out


def resolve_cursor_job_cfg(
    text: str,
    *,
    channel_id: str = "",
    thread_ts: str = "",
) -> dict[str, Any] | None:
    """Pin override, else repo resolve for coding asks (mount, cloud URL, or thread history)."""
    pin = match_cursor_thread(channel_id, thread_ts)
    if pin:
        return coerce_cloud_when_mount_missing(pin, text)
    # Do not sole-default on short follow-ups — that steals "fix it all" onto the wrong repo.
    cfg = match_cursor_repo(text, allow_sole_default=False)
    if cfg:
        return coerce_cloud_when_mount_missing(cfg, text)
    if channel_id and thread_ts:
        blob = thread_coding_context_blob(
            {"slack_channel_id": channel_id, "slack_thread_ts": thread_ts}
        )
        if blob:
            hist = match_cursor_repo(blob, allow_sole_default=False)
            if hist:
                return coerce_cloud_when_mount_missing(hist, text)
    sole = match_cursor_repo(text, allow_sole_default=True)
    return coerce_cloud_when_mount_missing(sole, text) if sole else None


def ambiguous_repo_message() -> str:
    repos = load_cursor_repos()
    if not repos:
        return (
            "Coding work needs a configured repo. "
            "Add a `repos:` entry in `config/cursor_threads.yaml`."
        )
    lines = ["Which repo should Tempa work on? Configured:"]
    for row in repos:
        aliases = ", ".join(row.get("aliases") or [row.get("id") or "?"])
        label = row.get("label") or row.get("id") or row.get("local_cwd") or row.get("repo")
        lines.append(f"• *{label}* (`{aliases}`)")
    return "\n".join(lines)


RUMI_AGENT_LOCAL_CWD = "/repos/rumixtempa"


def rumi_agent_job_cfg() -> dict[str, Any]:
    """Fixed cfg for org-wide Rumi skills-pack jobs (never a PR/worktree target)."""
    return {
        "id": "rumixtempa",
        "local_cwd": RUMI_AGENT_LOCAL_CWD,
        "repo": "",
        "starting_ref": None,
        "label": "Rumi agent skills",
        "base_ref": "main",
        "jira_key": None,
        "required_checks": [],
        "aliases": ["rumixtempa", "agent-skills", "agent skills"],
        "job_kind": "rumi_agent",
    }


def _resolve_user_label(client: Any, user_id: str, cache: dict[str, str]) -> str:
    uid = str(user_id or "").strip()
    if not uid:
        return "?"
    if uid in cache:
        return cache[uid]
    try:
        from tempa.channels.slack.client import user_display_name

        info = client.users_info(user=uid)
        data = info.data if hasattr(info, "data") and isinstance(info.data, dict) else (
            info if isinstance(info, dict) else {}
        )
        user = data.get("user")
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


async def handle_cursor_job_message(
    text: str,
    context: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
) -> str | None:
    """Enqueue a durable Tempa Cursor job.

    Returns a short ack string for the Slack handler (or an error). The real
    answer is posted asynchronously by the Cursor worker.
    """
    from tempa.channels.slack import cursor_progress as prog
    from tempa.channels.slack.cursor_worker import enqueue_from_slack
    from tempa.qa.cursor import cursor_configured

    channel_id = str(context.get("slack_channel_id") or context.get("channel_id") or "")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    job_cfg = cfg or resolve_cursor_job_cfg(text, channel_id=channel_id, thread_ts=thread_ts)
    if not job_cfg:
        return None
    # Pins / callers may pass a cfg that still points at a dead mount.
    # Rumi skills pack has no GitHub cloud fallback — keep local_cwd.
    if str(job_cfg.get("job_kind") or "") != "rumi_agent":
        job_cfg = coerce_cloud_when_mount_missing(dict(job_cfg), text)
    else:
        job_cfg = dict(job_cfg)
    if not cursor_configured():
        from tempa.core.chat_errors import sanitize_user_error

        return f"_{sanitize_user_error('CURSOR_API_KEY is not configured on Tempa.')}_"

    local_cwd = str(job_cfg.get("local_cwd") or "").strip()
    if local_cwd and not Path(local_cwd).is_dir():
        from tempa.core.chat_errors import sanitize_user_error

        return f"_{sanitize_user_error(f'local repo path is not available (`{local_cwd}`).')}_"

    result = enqueue_from_slack(text=text, context=context, cfg=job_cfg)
    if result.get("error"):
        from tempa.core.chat_errors import slack_problem_message

        return slack_problem_message(str(result["error"]))
    if result.get("queued_position"):
        return prog.msg_queued(int(result["queued_position"]))
    if str(job_cfg.get("job_kind") or "") == "rumi_agent":
        return prog.msg_rumi_working()
    return prog.msg_working()


async def handle_cursor_thread_message(
    text: str,
    context: dict[str, Any],
) -> str | None:
    """Enqueue for a pinned thread (compatibility wrapper)."""
    channel_id = str(context.get("slack_channel_id") or context.get("channel_id") or "")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    cfg = match_cursor_thread(channel_id, thread_ts)
    if not cfg:
        return None
    return await handle_cursor_job_message(text, context, cfg=cfg)
