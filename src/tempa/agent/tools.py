"""Expose Tempa plugin tools as Cursor SDK CustomTools (local agents)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_plugins() -> None:
    from tempa.plugins.registry import list_tools, load_builtin_plugins

    if not list_tools():
        load_builtin_plugins()


def build_custom_tools(*, default_user_id: str = "") -> dict[str, Any]:
    """Map registered plugin tools → cursor_sdk.CustomTool dict."""
    from cursor_sdk import CustomTool, CustomToolContext

    from tempa.plugins.registry import list_tools, run_tool

    _ensure_plugins()
    out: dict[str, Any] = {}

    for meta in list_tools():
        name = str(meta.get("name") or "").strip()
        if not name:
            continue
        description = str(meta.get("description") or name)
        schema = meta.get("input_schema") or {"type": "object", "properties": {}}

        def _make_execute(tool_name: str):
            def execute(args: dict[str, Any], context: CustomToolContext) -> str:
                _ = context
                payload = dict(args or {})
                # Auto-tag preference writes with the requesting user when omitted.
                if (
                    tool_name == "memory.add_preference"
                    and default_user_id
                    and not str(payload.get("user_id") or "").strip()
                ):
                    payload["user_id"] = default_user_id
                try:
                    result = run_tool(tool_name, **payload)
                except TypeError:
                    # Some handlers reject unexpected kwargs — retry with schema keys only.
                    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
                    filtered = {k: v for k, v in payload.items() if k in props}
                    result = run_tool(tool_name, **filtered)
                except Exception as exc:
                    logger.exception("tool %s failed", tool_name)
                    result = {"status": "error", "reason": str(exc)}
                if isinstance(result, (dict, list)):
                    return json.dumps(result, default=str)[:12_000]
                return str(result)[:12_000]

            return execute

        # CustomTool keys must be valid identifiers — replace dots.
        key = name.replace(".", "_")
        out[key] = CustomTool(
            description=f"{name}: {description}",
            input_schema=schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
            execute=_make_execute(name),
        )
    return out
