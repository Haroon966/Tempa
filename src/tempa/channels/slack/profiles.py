"""Resolve + persist Slack user display names/avatars for Sessions."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from tempa.channels.slack.client import load_slack_client, user_display_name
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_mem: dict[str, dict[str, str]] = {}
_mem_loaded_at = 0.0
_MEM_TTL_S = 300.0


def _cache_path() -> Path:
    path = get_settings().sessions_dir / "slack" / "user_profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_disk() -> dict[str, dict[str, str]]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        profiles = raw.get("profiles") if isinstance(raw, dict) else raw
        if not isinstance(profiles, dict):
            return {}
        out: dict[str, dict[str, str]] = {}
        for uid, row in profiles.items():
            if not isinstance(row, dict):
                continue
            out[str(uid)] = {
                "name": str(row.get("name") or uid),
                "image": str(row.get("image") or ""),
            }
        return out
    except Exception:
        return {}


def _save_disk(profiles: dict[str, dict[str, str]]) -> None:
    path = _cache_path()
    payload = {"profiles": profiles, "updated_at": time.time()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _from_presence() -> dict[str, dict[str, str]]:
    try:
        from tempa.channels.slack.presence_store import load_members

        out: dict[str, dict[str, str]] = {}
        for member in load_members():
            uid = str(member.get("user_id") or "").strip()
            if not uid:
                continue
            out[uid] = {
                "name": str(member.get("name") or uid),
                "image": str(member.get("image") or ""),
            }
        return out
    except Exception:
        return {}


def _response_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    return data if isinstance(data, dict) else {}


def _fetch_one(client: Any, user_id: str) -> dict[str, str] | None:
    try:
        info = _response_dict(client.users_info(user=user_id))
        user = info.get("user")
        if not isinstance(user, dict):
            return None
        profile = user.get("profile") or {}
        image = str(
            profile.get("image_192")
            or profile.get("image_72")
            or profile.get("image_48")
            or ""
        )
        return {
            "name": user_display_name(user),
            "image": image,
        }
    except Exception:
        logger.debug("users_info failed for %s", user_id, exc_info=True)
        return None


def _ensure_mem() -> dict[str, dict[str, str]]:
    global _mem, _mem_loaded_at
    now = time.time()
    with _lock:
        if now - _mem_loaded_at > _MEM_TTL_S or not _mem:
            merged = _load_disk()
            for uid, row in _from_presence().items():
                prev = merged.get(uid) or {}
                merged[uid] = {
                    "name": row.get("name") or prev.get("name") or uid,
                    "image": row.get("image") or prev.get("image") or "",
                }
            _mem = merged
            _mem_loaded_at = now
        return _mem


def remember_profile(user_id: str) -> dict[str, str] | None:
    """Fetch + permanently cache one Slack profile (name + avatar)."""
    uid = str(user_id or "").strip()
    if not uid:
        return None
    mem = _ensure_mem()
    cached = mem.get(uid)
    if cached and cached.get("name") and cached["name"] != uid and cached.get("image"):
        return dict(cached)
    client = load_slack_client()
    if client is None:
        return dict(cached) if cached else None
    fetched = _fetch_one(client, uid)
    if not fetched:
        return dict(cached) if cached else None
    with _lock:
        _mem[uid] = fetched
        _save_disk(_mem)
    return dict(fetched)


def resolve_profiles(user_ids: Iterable[str]) -> dict[str, dict[str, str]]:
    """Return {user_id: {name, image}} for the given Slack user ids."""
    wanted = sorted({str(u or "").strip() for u in user_ids if str(u or "").strip()})
    if not wanted:
        return {}

    mem = _ensure_mem()
    found: dict[str, dict[str, str]] = {}
    missing: list[str] = []
    for uid in wanted:
        row = mem.get(uid)
        if row and row.get("name") and row["name"] != uid and row.get("image"):
            found[uid] = dict(row)
        elif row and row.get("name") and row["name"] != uid:
            found[uid] = dict(row)
            if not row.get("image"):
                missing.append(uid)
        else:
            missing.append(uid)

    if missing:
        client = load_slack_client()
        if client is not None:
            updates: dict[str, dict[str, str]] = {}
            for uid in missing:
                fetched = _fetch_one(client, uid)
                if fetched:
                    updates[uid] = fetched
                    found[uid] = fetched
            if updates:
                with _lock:
                    _mem.update(updates)
                    _save_disk(_mem)

    for uid in wanted:
        if uid not in found:
            found[uid] = {"name": uid, "image": ""}
    return found


def participant_ids_for_job(job: dict[str, Any]) -> list[str]:
    """Ordered unique human ids for a job (starter first)."""
    from tempa.channels.slack.conversation import participants_from_turns

    starter = str(job.get("user_id") or "").strip()
    stored = [str(u).strip() for u in (job.get("participant_ids") or []) if str(u).strip()]
    return participants_from_turns(
        [{"role": "user", "user_id": uid} for uid in stored],
        starter_user_id=starter,
    ) or ([starter] if starter else [])


def backfill_participant_ids(jobs: list[dict[str, Any]]) -> None:
    """One-time repair: seed missing participant_ids from conversation.jsonl and persist."""
    from tempa.channels.slack.conversation import (
        participants_for_threads,
        participants_from_turns,
        thread_key,
    )
    from tempa.channels.slack.cursor_jobs import add_thread_participants

    need = [
        j
        for j in jobs
        if not (j.get("participant_ids") or [])
        and str(j.get("channel_id") or "").strip()
        and str(j.get("thread_ts") or "").strip()
    ]
    if not need:
        return
    by_thread = participants_for_threads(
        [
            (str(j.get("channel_id") or ""), str(j.get("thread_ts") or ""))
            for j in need
        ]
    )
    for job in need:
        ch = str(job.get("channel_id") or "").strip()
        ts = str(job.get("thread_ts") or "").strip()
        starter = str(job.get("user_id") or "").strip()
        key = thread_key(channel_id=ch, thread_ts=ts)
        from_thread = by_thread.get(key) or by_thread.get(ch) or []
        ids = participants_from_turns(
            [{"role": "user", "user_id": uid} for uid in from_thread],
            starter_user_id=starter,
        )
        if not ids and starter:
            ids = [starter]
        if not ids:
            continue
        job["participant_ids"] = ids
        try:
            add_thread_participants(channel_id=ch, thread_ts=ts, user_ids=ids)
        except Exception:
            logger.debug("backfill participant_ids failed", exc_info=True)


def sync_participants_from_slack(*, channel_id: str, thread_ts: str) -> list[str]:
    """Source of truth: Slack thread replies → human user ids (persisted on jobs)."""
    ch = str(channel_id or "").strip()
    ts = str(thread_ts or "").strip()
    if not ch or not ts:
        return []
    client = load_slack_client()
    if client is None:
        return []
    try:
        response = _response_dict(
            client.conversations_replies(channel=ch, ts=ts, limit=200)
        )
        messages = list(response.get("messages") or [])
    except Exception:
        logger.debug("conversations.replies failed for %s/%s", ch, ts, exc_info=True)
        return []

    ordered: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("bot_id") or msg.get("subtype") in {
            "bot_message",
            "channel_join",
            "channel_leave",
            "message_deleted",
        }:
            continue
        uid = str(msg.get("user") or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)

    if ordered:
        try:
            from tempa.channels.slack.cursor_jobs import add_thread_participants

            add_thread_participants(channel_id=ch, thread_ts=ts, user_ids=ordered)
        except Exception:
            logger.debug("persist slack participants failed", exc_info=True)
        resolve_profiles(ordered)
    return ordered


def _participants_payload(ids: list[str], profiles: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "user_id": uid,
            "name": (profiles.get(uid) or {}).get("name") or uid,
            "image": (profiles.get(uid) or {}).get("image") or "",
        }
        for uid in ids
    ]


def enrich_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach user_name/user_image + participants[] from persisted participant_ids."""
    backfill_participant_ids(jobs)

    all_ids: list[str] = []
    per_job_ids: list[list[str]] = []
    for job in jobs:
        ids = participant_ids_for_job(job)
        per_job_ids.append(ids)
        all_ids.extend(ids)

    profiles = resolve_profiles(all_ids)
    out: list[dict[str, Any]] = []
    for job, ids in zip(jobs, per_job_ids):
        row = dict(job)
        starter = str(row.get("user_id") or "").strip()
        participants = _participants_payload(ids, profiles)
        row["participant_ids"] = ids
        row["participants"] = participants
        primary = next((p for p in participants if p["user_id"] == starter), None)
        if primary is None and participants:
            primary = participants[0]
        if primary:
            row["user_name"] = primary["name"]
            if primary.get("image"):
                row["user_image"] = primary["image"]
        out.append(row)
    return out


def enrich_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles = resolve_profiles(
        str(t.get("user_id") or "") for t in turns if t.get("role") != "assistant"
    )
    out: list[dict[str, Any]] = []
    for turn in turns:
        row = dict(turn)
        if str(row.get("role") or "") == "assistant":
            row["user_name"] = "Tempa"
            out.append(row)
            continue
        uid = str(row.get("user_id") or "").strip()
        profile = profiles.get(uid) or {}
        if profile.get("name"):
            row["user_name"] = profile["name"]
        if profile.get("image"):
            row["user_image"] = profile["image"]
        out.append(row)
    return out


def participants_from_enriched_turns(
    turns: list[dict[str, Any]],
    *,
    starter_user_id: str = "",
) -> list[dict[str, str]]:
    """Build participants[] from already-enriched conversation turns."""
    from tempa.channels.slack.conversation import participants_from_turns

    ids = participants_from_turns(turns, starter_user_id=starter_user_id)
    by_id: dict[str, dict[str, str]] = {}
    for turn in turns:
        if str(turn.get("role") or "") == "assistant":
            continue
        uid = str(turn.get("user_id") or "").strip()
        if not uid or uid in by_id:
            continue
        by_id[uid] = {
            "user_id": uid,
            "name": str(turn.get("user_name") or uid),
            "image": str(turn.get("user_image") or ""),
        }
    profiles = resolve_profiles(uid for uid in ids if uid not in by_id)
    out: list[dict[str, str]] = []
    for uid in ids:
        if uid in by_id:
            out.append(by_id[uid])
            continue
        profile = profiles.get(uid) or {}
        out.append(
            {
                "user_id": uid,
                "name": profile.get("name") or uid,
                "image": profile.get("image") or "",
            }
        )
    return out
