from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings


def _profiles_path() -> Path:
    path = get_settings().sessions_dir / "jira" / "user_profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_all() -> dict[str, dict[str, Any]]:
    path = _profiles_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_all(profiles: dict[str, dict[str, Any]]) -> None:
    _profiles_path().write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")


def _profile_key(slack_user_id: str | None = None, *, session_id: str = "") -> str:
    if slack_user_id:
        return f"slack:{slack_user_id}"
    if session_id:
        return f"dashboard:{session_id}"
    return ""


def get_profile(*, slack_user_id: str = "", session_id: str = "") -> dict[str, Any] | None:
    key = _profile_key(slack_user_id or None, session_id=session_id)
    if not key:
        return None
    profile = _load_all().get(key)
    return dict(profile) if profile else None


def save_profile(
    *,
    slack_user_id: str = "",
    session_id: str = "",
    jira_account_id: str = "",
    jira_email: str = "",
    display_name: str = "",
    default_project: str = "",
    source: str = "user_provided",
) -> dict[str, Any]:
    key = _profile_key(slack_user_id or None, session_id=session_id)
    if not key:
        raise ValueError("slack_user_id or session_id required")
    profiles = _load_all()
    existing = dict(profiles.get(key) or {})
    if jira_account_id:
        existing["jira_account_id"] = jira_account_id
    if jira_email:
        existing["jira_email"] = jira_email
    if display_name:
        existing["display_name"] = display_name
    if default_project:
        existing["default_project"] = default_project
    existing["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    existing["source"] = source
    profiles[key] = existing
    _save_all(profiles)
    return existing


def remember_jira_email(
    *,
    slack_user_id: str = "",
    session_id: str = "",
    email: str,
    account_id: str = "",
) -> dict[str, Any]:
    return save_profile(
        slack_user_id=slack_user_id,
        session_id=session_id,
        jira_email=email.strip(),
        jira_account_id=account_id,
        source="user_provided",
    )
