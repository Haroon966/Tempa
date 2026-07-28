from __future__ import annotations

import json
from pathlib import Path

from tempa.security.sessions import delete_secret_file, read_secret_file, write_secret_file
from tempa.settings import get_settings


def _config_path() -> Path:
    return get_settings().sessions_dir / "coolify" / "config.json"


def load_coolify_session_config() -> dict[str, str]:
    settings = get_settings()
    base: dict[str, str] = {
        "base_url": settings.coolify_base_url.strip(),
        "server_uuid": settings.coolify_server_uuid.strip(),
        "project_uuid": settings.coolify_project_uuid.strip(),
        "github_app_uuid": settings.coolify_github_app_uuid.strip(),
        "deploy_key_uuid": settings.coolify_deploy_key_uuid.strip(),
    }
    path = _config_path()
    if not path.exists():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in (
                "base_url",
                "server_uuid",
                "project_uuid",
                "github_app_uuid",
                "deploy_key_uuid",
            ):
                if data.get(key):
                    base[key] = str(data[key]).strip()
    except (json.JSONDecodeError, OSError):
        pass
    return base


def save_coolify_session_config(
    *,
    base_url: str,
    server_uuid: str = "",
    project_uuid: str = "",
    github_app_uuid: str = "",
    deploy_key_uuid: str = "",
    api_token: str | None = None,
) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_coolify_session_config()
    path.write_text(
        json.dumps(
            {
                "base_url": base_url.strip().rstrip("/"),
                "server_uuid": server_uuid.strip() or existing.get("server_uuid", ""),
                "project_uuid": project_uuid.strip() or existing.get("project_uuid", ""),
                "github_app_uuid": github_app_uuid.strip()
                if github_app_uuid.strip()
                else existing.get("github_app_uuid", ""),
                "deploy_key_uuid": deploy_key_uuid.strip()
                if deploy_key_uuid.strip()
                else existing.get("deploy_key_uuid", ""),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if api_token is not None and api_token.strip():
        write_secret_file("coolify.token", api_token.strip())


def clear_coolify_session() -> None:
    path = _config_path()
    if path.exists():
        path.unlink()
    delete_secret_file("coolify.token")


def load_coolify_api_token() -> str:
    settings = get_settings()
    if settings.coolify_api_token.strip():
        return settings.coolify_api_token.strip()
    return read_secret_file("coolify.token")
