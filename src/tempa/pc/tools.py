from __future__ import annotations

from typing import Any

from tempa.pc import apps, browser, files, shell
from tempa.rag.ingest import ingest_text

CONFIRMATION_TOOLS = frozenset({"write_file", "patch_file", "create_directory", "delete_path", "prepare_file_transfer"})


def run_pc_tool(tool: str, **kwargs) -> dict:
    if tool in CONFIRMATION_TOOLS:
        return {
            "status": "pending_confirmation",
            "msg": f"Tool {tool} requires user approval via pending action",
        }
    return run_pc_tool_confirmed(tool, **kwargs)


def run_pc_tool_confirmed(tool: str, **kwargs) -> dict:
    from tempa.core.audit import log_pc_action

    if tool == "run_shell":
        result = shell.run_shell(kwargs.get("command", ""))
    elif tool == "read_file":
        result = files.read_file(kwargs.get("path", ""), kwargs.get("start", 1), kwargs.get("count", 200))
    elif tool == "write_file":
        result = files.write_file(kwargs.get("path", ""), kwargs.get("content", ""))
        log_pc_action("write_file", kwargs.get("path", ""), result=result)
    elif tool == "patch_file":
        result = files.patch_file(
            kwargs.get("path", ""),
            kwargs.get("old_content", ""),
            kwargs.get("new_content", ""),
        )
        log_pc_action("patch_file", kwargs.get("path", ""), result=result)
    elif tool == "create_directory":
        result = files.create_directory(kwargs.get("path", ""))
        log_pc_action("create_directory", kwargs.get("path", ""), result=result)
    elif tool == "delete_path":
        result = files.delete_path(kwargs.get("path", ""))
        log_pc_action("delete_path", kwargs.get("path", ""), result=result)
    elif tool == "open_app":
        result = apps.open_app(kwargs.get("name", ""))
    elif tool == "close_app":
        result = apps.close_app(kwargs.get("name", ""))
    elif tool == "browser_navigate":
        result = browser.browser_navigate(kwargs.get("url", ""))
    elif tool == "browser_execute_js":
        result = browser.browser_execute_js(kwargs.get("url", ""), kwargs.get("script", ""))
    elif tool == "prepare_file_transfer":
        result = {"status": "pending_confirmation", "path": kwargs.get("path", "")}
    else:
        result = {"status": "error", "msg": f"Unknown PC tool: {tool}"}

    if tool != "prepare_file_transfer":
        ingest_text(
            f"PC tool {tool}: {result}",
            tool="pc",
            source=tool,
            tags=["action"],
        )
    return result


def request_pc_confirmation(tool: str, **kwargs) -> dict[str, Any]:
    from tempa.core.notifications import notify
    from tempa.core.pending_actions import create_pending_action
    import asyncio

    type_map = {
        "write_file": "pc_write",
        "patch_file": "pc_write",
        "create_directory": "pc_mkdir",
        "delete_path": "pc_delete",
        "prepare_file_transfer": "file_transfer",
    }
    action_type = type_map.get(tool)
    if not action_type:
        return run_pc_tool_confirmed(tool, **kwargs)

    payload = dict(kwargs)
    if tool == "patch_file":
        payload = {
            "path": kwargs.get("path", ""),
            "content": kwargs.get("new_content", ""),
            "op": "patch",
            "old_content": kwargs.get("old_content", ""),
        }
    if tool == "prepare_file_transfer":
        payload = {"path": kwargs.get("path", ""), "filename": kwargs.get("path", "").split("/")[-1]}

    action = create_pending_action(action_type, payload, source_channel="pc", risk_level="high")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            notify(
                "pending_action",
                title="Action needs approval",
                body=action.get("title", "PC action pending"),
                pending_action_id=action["id"],
            )
        )
    except RuntimeError:
        pass
    return {
        "status": "pending",
        "pending_action_id": action["id"],
        "title": action.get("title"),
        "msg": "Awaiting user confirmation in Tempa dashboard or extension",
    }
