from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tempa.plugins import get_plugin_store, load_tools_config
from tempa.rag.ingest import ingest_text

logger = logging.getLogger(__name__)


@dataclass
class PluginTool:
    name: str
    description: str
    handler: Callable[..., Any]
    input_schema: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, PluginTool] = {}


def register_tool(
    name: str,
    description: str,
    handler: Callable[..., Any],
    *,
    input_schema: dict[str, Any] | None = None,
) -> None:
    """FR-PLUGIN-01: register a plugin tool with name, description, schema, handler."""
    get_plugin_store()
    _REGISTRY[name] = PluginTool(
        name=name,
        description=description,
        handler=handler,
        input_schema=input_schema or {"type": "object", "properties": {}},
    )


def list_tools() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in _REGISTRY.values()
    ]


def run_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    tool = _REGISTRY.get(name)
    if not tool:
        return {"status": "error", "msg": f"Unknown tool: {name}"}
    result = tool.handler(**kwargs)
    if not isinstance(result, dict):
        result = {"status": "ok", "result": result}
    ingest_text(
        f"Plugin {name}: {result}",
        tool="plugin",
        source=name,
        tags=["plugin", "action"],
    )
    return result


def load_builtin_plugins() -> None:
    """FR-PLUGIN-02/03: load builtin modules from tools.yaml."""
    from tempa.plugins.builtins import register_builtin_tools

    register_builtin_tools()
    config = load_tools_config()
    for mod_name in config.get("plugins", {}).get("builtin", []):
        try:
            importlib.import_module(mod_name)
        except Exception:
            logger.warning("Failed to load plugin module %s", mod_name)
    for mod_name in config.get("plugins", {}).get("enabled", []):
        try:
            importlib.import_module(mod_name)
        except Exception:
            logger.warning("Failed to load enabled plugin %s", mod_name)


def _register_builtins() -> None:
    """Legacy entry — builtins register via load_builtin_plugins."""
    pass
