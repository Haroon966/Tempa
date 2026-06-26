from __future__ import annotations

import json
from pathlib import Path

from tempa.security.sessions import delete_secret_file, read_secret_file, write_secret_file
from tempa.settings import get_settings


def _config_path() -> Path:
    return get_settings().sessions_dir / "jira" / "config.json"


def load_jira_session_config() -> dict[str, str]:
    settings = get_settings()
    base: dict[str, str] = {
        "base_url": settings.jira_base_url.strip(),
        "email": settings.jira_email.strip(),
        "default_project": settings.jira_default_project.strip(),
    }
    path = _config_path()
    if not path.exists():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("base_url", "email", "default_project"):
                if data.get(key):
                    base[key] = str(data[key]).strip()
    except (json.JSONDecodeError, OSError):
        pass
    return base


def save_jira_session_config(
    *,
    base_url: str,
    email: str,
    default_project: str = "",
    api_token: str | None = None,
) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "base_url": base_url.strip().rstrip("/"),
                "email": email.strip(),
                "default_project": default_project.strip(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if api_token is not None and api_token.strip():
        write_secret_file("jira.token", api_token.strip())


def clear_jira_session() -> None:
    path = _config_path()
    if path.exists():
        path.unlink()
    delete_secret_file("jira.token")


def load_jira_api_token() -> str:
    settings = get_settings()
    if settings.jira_api_token.strip():
        return settings.jira_api_token.strip()
    return read_secret_file("jira.token")
