from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.gmail.ingest import ingest_gmail_message
from tempa.channels.gmail.oauth import load_gmail_client
from tempa.core.notifications import notify
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def _sync_state_path() -> Path:
    return get_settings().sessions_dir / "gmail" / "sync_state.json"


def _load_config() -> dict[str, Any]:
    try:
        import yaml

        path = get_settings().config_dir / "permissions.yaml"
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("gmail") or {}
    except Exception:
        return {}


def load_sync_state() -> dict[str, Any]:
    path = _sync_state_path()
    if not path.exists():
        return {"history_id": "", "seen_message_ids": [], "last_sync_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "history_id": str(data.get("history_id") or ""),
            "seen_message_ids": list(data.get("seen_message_ids") or []),
            "last_sync_at": str(data.get("last_sync_at") or ""),
        }
    except Exception:
        return {"history_id": "", "seen_message_ids": [], "last_sync_at": ""}


def save_sync_state(state: dict[str, Any]) -> None:
    path = _sync_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def sync_once(*, full: bool = False) -> dict[str, Any]:
    import asyncio

    client = load_gmail_client()
    if client is None:
        return {"status": "skipped", "reason": "Gmail not connected"}

    cfg = _load_config()
    max_messages = int(cfg.get("max_messages_per_sync", 50))
    state = load_sync_state()
    seen = set(state.get("seen_message_ids") or [])
    new_ids: list[str] = []

    try:
        profile = await asyncio.to_thread(client.get_profile)
        current_history_id = str(profile.get("historyId") or "")
    except Exception as exc:
        logger.exception("Gmail profile fetch failed")
        return {"status": "error", "reason": str(exc)}

    history_id = state.get("history_id") or ""
    if full or not history_id:
        try:
            ids = await asyncio.to_thread(client.list_messages, query="is:unread", max_results=max_messages)
            new_ids = [mid for mid in ids if mid not in seen]
        except Exception as exc:
            return {"status": "error", "reason": str(exc)}
    else:
        try:
            history = await asyncio.to_thread(client.list_history, history_id, max_results=max_messages)
            new_ids = [mid for mid in history.get("message_ids", []) if mid not in seen]
            if history.get("history_id"):
                current_history_id = history["history_id"]
        except Exception as exc:
            err = str(exc)
            if "404" in err or "historyId" in err.lower():
                ids = await asyncio.to_thread(
                    client.list_messages, query="newer_than:7d", max_results=max_messages
                )
                new_ids = [mid for mid in ids if mid not in seen]
            else:
                return {"status": "error", "reason": err}

    ingested = 0
    notified = 0
    for mid in new_ids[:max_messages]:
        try:
            msg = await asyncio.to_thread(client.get_message_metadata, mid)
            await asyncio.to_thread(ingest_gmail_message, msg, tags=["sync"])
            seen.add(mid)
            ingested += 1
            unread = "UNREAD" in (msg.label_ids or [])
            if unread:
                await notify(
                    "new_email",
                    title="New email",
                    body=f"{msg.sender}: {msg.subject}",
                    extra={"message_id": mid, "from": msg.sender, "subject": msg.subject},
                )
                notified += 1
        except Exception:
            logger.exception("Failed to sync message %s", mid)

    state["history_id"] = current_history_id
    state["seen_message_ids"] = list(seen)[-5000:]
    state["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    save_sync_state(state)

    snapshot_result: dict[str, Any] = {}
    try:
        from tempa.channels.gmail.snapshot import refresh_gmail_snapshot

        snapshot_result = await asyncio.to_thread(refresh_gmail_snapshot)
    except Exception:
        logger.exception("Gmail snapshot refresh failed")

    return {
        "status": "ok",
        "new_messages": ingested,
        "notifications": notified,
        "history_id": current_history_id,
        "snapshot": snapshot_result,
    }
