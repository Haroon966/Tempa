from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.jira.client import jira_configured, list_assignable_users, search_users
from tempa.channels.jira.session import load_jira_session_config
from tempa.core.sync_status import record_sync
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def _sync_state_path() -> Path:
    path = get_settings().sessions_dir / "jira" / "sync_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_sync_state() -> dict[str, Any]:
    path = _sync_state_path()
    if not path.exists():
        return {"last_sync_at": "", "user_count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "last_sync_at": str(data.get("last_sync_at") or ""),
            "user_count": int(data.get("user_count") or 0),
        }
    except Exception:
        return {"last_sync_at": "", "user_count": 0}


def save_sync_state(state: dict[str, Any]) -> None:
    _sync_state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _project_keys() -> list[str]:
    keys: list[str] = []
    cfg = load_jira_session_config()
    default = str(cfg.get("default_project") or "").strip()
    if default:
        keys.append(default)
    settings = get_settings()
    if settings.jira_default_project and settings.jira_default_project not in keys:
        keys.append(settings.jira_default_project)
    try:
        from tempa.varys.config import load_varys_config

        for key in load_varys_config().jira_projects:
            if key and key not in keys:
                keys.append(key)
    except Exception:
        pass
    return keys


def sync_jira_users_blocking() -> dict[str, Any]:
    if not jira_configured():
        return {"status": "skipped", "reason": "Jira not configured"}

    seen: dict[str, dict[str, Any]] = {}
    projects = _project_keys()

    for project in projects:
        try:
            for user in list_assignable_users(project, max_results=1000):
                aid = user.get("account_id") or ""
                if aid:
                    seen[aid] = user
        except Exception as exc:
            logger.warning("Jira assignable user sync failed for %s: %s", project, exc)

    if not seen:
        try:
            for user in search_users(".", max_results=1000):
                aid = user.get("account_id") or ""
                if aid:
                    seen[aid] = user
        except Exception as exc:
            logger.warning("Jira user search fallback failed: %s", exc)

    contacts = [
        {
            "id": f"jira:{user['account_id']}",
            "name": user.get("display_name") or "",
            "email": user.get("email") or "",
            "source": "jira",
        }
        for user in seen.values()
        if user.get("account_id")
    ]

    count = 0
    if contacts:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def _upsert():
            from tempa.channels.contacts.store import upsert_contacts

            return await upsert_contacts(contacts)

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                count = pool.submit(asyncio.run, _upsert()).result(timeout=60)
        else:
            count = asyncio.run(_upsert())

    from tempa.channels.contacts.linker import link_identities

    link_result = link_identities()
    now = datetime.now(timezone.utc).isoformat()
    state = {"last_sync_at": now, "user_count": len(contacts)}
    save_sync_state(state)
    record_sync(
        "jira_users",
        status="ok",
        details={"user_count": len(contacts), "identity_link_count": link_result.get("identity_link_count", 0)},
    )
    return {
        "status": "ok",
        "count": count or len(contacts),
        "user_count": len(contacts),
        "identity_link_count": link_result.get("identity_link_count", 0),
        "last_sync_at": now,
    }


async def sync_jira_users() -> dict[str, Any]:
    return await asyncio.to_thread(sync_jira_users_blocking)


def _is_stale(max_age_hours: float) -> bool:
    state = load_sync_state()
    last = state.get("last_sync_at") or ""
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - dt
        return age.total_seconds() > max_age_hours * 3600
    except ValueError:
        return True


async def ensure_jira_users_fresh(*, max_age_hours: float = 24) -> dict[str, Any] | None:
    if not jira_configured():
        return None
    if not _is_stale(max_age_hours):
        return None
    return await sync_jira_users()


async def ensure_contacts_fresh(*, max_age_hours: float = 24) -> dict[str, Any] | None:
    """Refresh Slack/Gmail contacts if stale (uses contacts sync state from slack sync)."""
    from tempa.channels.slack.sync import load_sync_state as slack_state

    state = slack_state()
    last = state.get("last_sync_at") or ""
    if last:
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - dt
            if age.total_seconds() <= max_age_hours * 3600:
                return None
        except ValueError:
            pass
    from tempa.channels.contacts.sync import sync_contacts

    return await sync_contacts()
