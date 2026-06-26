from __future__ import annotations

from typing import Any

from tempa.channels.jira.client import jira_configured, test_connection
from tempa.channels.jira.session import load_jira_session_config
from tempa.settings import get_settings


def jira_connection_status() -> dict[str, Any]:
    settings = get_settings()
    cfg = load_jira_session_config()
    configured = jira_configured()
    if not configured:
        missing = []
        if not cfg.get("base_url"):
            missing.append("base_url")
        if not cfg.get("email"):
            missing.append("email")
        if not settings.jira_api_token.strip():
            from tempa.channels.jira.session import load_jira_api_token

            if not load_jira_api_token():
                missing.append("api_token")
        detail = "Set Jira base URL, email, and API token"
        if missing:
            detail = f"Missing: {', '.join(missing)}"
        return {
            "connected": False,
            "configured": False,
            "status": "disconnected",
            "detail": detail,
            "base_url": cfg.get("base_url", ""),
            "email": cfg.get("email", ""),
            "default_project": cfg.get("default_project", ""),
            "enabled": settings.jira_enabled,
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
                "email": cfg.get("email", ""),
                "default_project": cfg.get("default_project", ""),
                "enabled": settings.jira_enabled,
            }
        return {
            "connected": True,
            "configured": True,
            "status": "connected",
            "detail": result.get("display_name") or result.get("email") or "Connected",
            "site": cfg.get("base_url", ""),
            "base_url": cfg.get("base_url", ""),
            "email": cfg.get("email", ""),
            "default_project": cfg.get("default_project", ""),
            "display_name": result.get("display_name", ""),
            "enabled": settings.jira_enabled,
        }
    except Exception as exc:
        return {
            "connected": False,
            "configured": True,
            "status": "error",
            "detail": str(exc)[:200],
            "base_url": cfg.get("base_url", ""),
            "email": cfg.get("email", ""),
            "default_project": cfg.get("default_project", ""),
            "enabled": settings.jira_enabled,
        }
