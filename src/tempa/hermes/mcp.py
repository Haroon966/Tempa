"""MCP client config for Tempa (Hermes Phase 3).

Loads servers from config/mcp.yaml. When the optional `mcp` package is installed,
tools can be listed/called. Otherwise config is validated and exposed for dashboard.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def mcp_config_path() -> Path:
    from tempa.settings import get_settings

    return get_settings().config_dir / "mcp.yaml"


def load_mcp_servers() -> list[dict[str, Any]]:
    path = mcp_config_path()
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception("Failed to load MCP config")
        return []
    servers = data.get("servers") if isinstance(data, dict) else data
    if not isinstance(servers, list):
        return []
    return [s for s in servers if isinstance(s, dict) and s.get("name")]


def mcp_available() -> bool:
    try:
        import mcp  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


async def list_mcp_tools() -> list[dict[str, Any]]:
    """Best-effort tool listing; returns empty if MCP SDK or servers unavailable."""
    servers = load_mcp_servers()
    if not servers:
        return []
    if not mcp_available():
        return [
            {
                "server": s.get("name"),
                "status": "configured",
                "detail": "Install mcp package to call tools",
            }
            for s in servers
        ]

    # Full stdio MCP handshake is server-specific; expose configured commands for now.
    out: list[dict[str, Any]] = []
    for s in servers:
        out.append(
            {
                "server": s.get("name"),
                "command": s.get("command"),
                "args": s.get("args") or [],
                "status": "ready" if s.get("command") else "incomplete",
            }
        )
    return out


async def call_mcp_tool(server: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Placeholder call path — requires mcp SDK + running server.

    Permanent hook for Hermes/Tempa; returns structured error instead of raising.
    """
    servers = {str(s.get("name")): s for s in load_mcp_servers()}
    conf = servers.get(server)
    if not conf:
        return {"status": "error", "reason": f"Unknown MCP server: {server}"}
    if not mcp_available():
        return {
            "status": "error",
            "reason": "mcp package not installed",
            "hint": "pip install mcp",
        }
    return {
        "status": "error",
        "reason": "MCP call transport not started for this process",
        "server": server,
        "tool": tool,
        "arguments": arguments or {},
        "config": {"command": conf.get("command"), "args": conf.get("args") or []},
    }


def mcp_status() -> dict[str, Any]:
    return {
        "sdk_installed": mcp_available(),
        "servers": load_mcp_servers(),
        "config_path": str(mcp_config_path()),
    }
