from __future__ import annotations

from typing import Any

from tempa.channels.coolify.client import coolify_configured, test_connection
from tempa.channels.coolify.session import load_coolify_api_token, load_coolify_session_config
from tempa.settings import get_settings


def coolify_connection_status() -> dict[str, Any]:
    settings = get_settings()
    cfg = load_coolify_session_config()
    configured = coolify_configured()
    if not configured:
        missing = []
        if not cfg.get("base_url"):
            missing.append("base_url")
        if not load_coolify_api_token():
            missing.append("api_token")
        detail = "Set Coolify base URL and API token"
        if missing:
            detail = f"Missing: {', '.join(missing)}"
        return {
            "connected": False,
            "configured": False,
            "status": "disconnected",
            "detail": detail,
            "base_url": cfg.get("base_url", ""),
            "server_uuid": cfg.get("server_uuid", ""),
            "project_uuid": cfg.get("project_uuid", ""),
            "github_app_uuid": cfg.get("github_app_uuid", ""),
            "deploy_key_uuid": cfg.get("deploy_key_uuid", ""),
            "enabled": settings.coolify_enabled,
        }
    try:
        result = test_connection()
        if result.get("status") != "ok":
            return {
                "connected": False,
                "configured": True,
                "status": "error",
                "detail": result.get("reason", "Connection test failed"),
                "base_url": cfg.get("base_url", ""),
                "server_uuid": cfg.get("server_uuid", ""),
                "project_uuid": cfg.get("project_uuid", ""),
                "github_app_uuid": cfg.get("github_app_uuid", ""),
                "deploy_key_uuid": cfg.get("deploy_key_uuid", ""),
                "enabled": settings.coolify_enabled,
            }
        detail = f"Coolify {result.get('version', '?')}"
        usable = result.get("usable_servers")
        if usable is not None:
            detail += f" · {usable} usable server(s)"
        return {
            "connected": True,
            "configured": True,
            "status": "connected",
            "detail": detail,
            "version": result.get("version", ""),
            "base_url": cfg.get("base_url", ""),
            "server_uuid": cfg.get("server_uuid", ""),
            "project_uuid": cfg.get("project_uuid", ""),
            "github_app_uuid": cfg.get("github_app_uuid", ""),
            "deploy_key_uuid": cfg.get("deploy_key_uuid", ""),
            "enabled": settings.coolify_enabled,
        }
    except Exception as exc:
        return {
            "connected": False,
            "configured": True,
            "status": "error",
            "detail": str(exc)[:200],
            "base_url": cfg.get("base_url", ""),
            "server_uuid": cfg.get("server_uuid", ""),
            "project_uuid": cfg.get("project_uuid", ""),
            "github_app_uuid": cfg.get("github_app_uuid", ""),
            "deploy_key_uuid": cfg.get("deploy_key_uuid", ""),
            "enabled": settings.coolify_enabled,
        }
