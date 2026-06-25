from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from tempa.settings import get_settings

logger = logging.getLogger(__name__)

PendingActionType = Literal[
    "email_send",
    "whatsapp_send",
    "slack_send",
    "pc_write",
    "pc_delete",
    "pc_mkdir",
    "file_transfer",
    "plan_preview",
    "qa_autofix",
]
PendingActionStatus = Literal["pending", "approved", "rejected", "expired", "failed", "executed"]

_lock = threading.Lock()

ACTION_TYPES: set[str] = {
    "email_send",
    "whatsapp_send",
    "slack_send",
    "pc_write",
    "pc_delete",
    "pc_mkdir",
    "file_transfer",
    "plan_preview",
    "qa_autofix",
}


def _store_path() -> Any:
    return get_settings().sessions_dir / "pending_actions.json"


def _ttl_seconds() -> int:
    try:
        import yaml

        path = get_settings().config_dir / "permissions.yaml"
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return int(data.get("pending_action_ttl_seconds", 3600))
    except Exception:
        return 3600


def _ensure_dir() -> None:
    _store_path().parent.mkdir(parents=True, exist_ok=True)


def _read_all_unlocked() -> dict[str, dict[str, Any]]:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_all_unlocked(actions: dict[str, dict[str, Any]]) -> None:
    _ensure_dir()
    _store_path().write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expire_stale_unlocked(actions: dict[str, dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc)
    for action in actions.values():
        if action.get("status") != "pending":
            continue
        expires_at = action.get("expires_at", "")
        if not expires_at:
            continue
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now >= exp:
                action["status"] = "expired"
                action["updated_at"] = _now_iso()
        except Exception:
            pass


def create_pending_action(
    action_type: str,
    payload: dict[str, Any],
    *,
    source_channel: str = "coordinator",
    risk_level: str = "medium",
    title: str = "",
) -> dict[str, Any]:
    if action_type not in ACTION_TYPES:
        raise ValueError(f"Unknown pending action type: {action_type}")

    action_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=_ttl_seconds())
    record = {
        "id": action_id,
        "type": action_type,
        "payload": payload,
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "source_channel": source_channel,
        "risk_level": risk_level,
        "title": title or _default_title(action_type, payload),
        "result": None,
    }
    with _lock:
        actions = _read_all_unlocked()
        _expire_stale_unlocked(actions)
        actions[action_id] = record
        _write_all_unlocked(actions)
    return dict(record)


def _default_title(action_type: str, payload: dict[str, Any]) -> str:
    if action_type == "email_send":
        return f"Email to {payload.get('to', 'unknown')}"
    if action_type == "whatsapp_send":
        return f"WhatsApp to {payload.get('number', 'unknown')}"
    if action_type == "slack_send":
        return f"Slack message to {payload.get('channel', 'unknown')}"
    if action_type == "file_transfer":
        return f"Transfer {payload.get('filename', payload.get('path', 'file'))}"
    if action_type.startswith("pc_"):
        return f"PC {action_type.replace('pc_', '')}: {payload.get('path', '')}"
    if action_type == "plan_preview":
        return "Review coordinator execution plan"
    if action_type == "qa_autofix":
        return f"QA fix: {payload.get('title', payload.get('file', 'patch'))}"
    return action_type


def list_pending_actions(*, status: str | None = "pending") -> list[dict[str, Any]]:
    with _lock:
        actions = _read_all_unlocked()
        _expire_stale_unlocked(actions)
        _write_all_unlocked(actions)
        items = list(actions.values())
    if status:
        items = [a for a in items if a.get("status") == status]
    items.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return items


def get_pending_action(action_id: str) -> dict[str, Any] | None:
    with _lock:
        actions = _read_all_unlocked()
        _expire_stale_unlocked(actions)
        _write_all_unlocked(actions)
        action = actions.get(action_id)
        return dict(action) if action else None


def update_pending_payload(action_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    with _lock:
        actions = _read_all_unlocked()
        action = actions.get(action_id)
        if not action or action.get("status") != "pending":
            return None
        action["payload"] = payload
        action["updated_at"] = _now_iso()
        actions[action_id] = action
        _write_all_unlocked(actions)
        return dict(action)


def reject_pending_action(action_id: str) -> dict[str, Any] | None:
    with _lock:
        actions = _read_all_unlocked()
        action = actions.get(action_id)
        if not action:
            return None
        if action.get("status") == "pending":
            action["status"] = "rejected"
            action["updated_at"] = _now_iso()
            actions[action_id] = action
            _write_all_unlocked(actions)
        return dict(action)


def _mark_action(action_id: str, status: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with _lock:
        actions = _read_all_unlocked()
        action = actions.get(action_id)
        if not action:
            return None
        action["status"] = status
        action["updated_at"] = _now_iso()
        if result is not None:
            action["result"] = result
        actions[action_id] = action
        _write_all_unlocked(actions)
        return dict(action)


async def execute_pending_action(action_id: str) -> dict[str, Any]:
    action = get_pending_action(action_id)
    if not action:
        return {"status": "error", "reason": "not_found"}
    if action.get("status") == "executed":
        return {"status": "executed", "result": action.get("result"), "idempotent": True}
    if action.get("status") != "pending":
        return {"status": "error", "reason": f"Action is {action.get('status')}"}

    _mark_action(action_id, "approved")
    try:
        result = await _run_executor(action["type"], action.get("payload") or {})
        if action["type"] != "plan_preview":
            _mark_action(action_id, "executed", result)
            from tempa.rag.procedural import capture_from_approval

            capture_from_approval(action["type"], action.get("payload") or {})
        else:
            _mark_action(action_id, "executed", result)
        return {"status": "executed", "result": result}
    except Exception as exc:
        logger.exception("Pending action execution failed: %s", action_id)
        _mark_action(action_id, "failed", {"status": "error", "reason": str(exc)})
        return {"status": "failed", "reason": str(exc)}


async def _run_executor(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action_type == "email_send":
        from tempa.channels.gmail.outbound import send_gmail_message

        result = await send_gmail_message(
            to=payload.get("to", ""),
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            html_body=payload.get("body_html") or None,
            cc=payload.get("cc", ""),
            bcc=payload.get("bcc", ""),
        )
        from tempa.channels.gmail.session_state import record_gmail_action

        record_gmail_action(result if isinstance(result, dict) else {"status": "sent"})
        return result
    if action_type == "whatsapp_send":
        from tempa.channels.whatsapp.outbound import send_whatsapp_media, send_whatsapp_message

        if payload.get("media_path"):
            return await send_whatsapp_media(
                payload.get("number", ""),
                payload.get("media_path", ""),
                caption=payload.get("text", ""),
                mediatype=payload.get("mediatype", "document"),
                require_user_confirmation=False,
            )
        return await send_whatsapp_message(
            payload.get("number", ""),
            payload.get("text", ""),
            require_user_confirmation=False,
        )
    if action_type == "slack_send":
        from tempa.channels.slack.outbound import send_slack_message

        return await send_slack_message(
            payload.get("channel", ""),
            payload.get("text", ""),
            thread_ts=str(payload.get("thread_ts") or ""),
            require_user_confirmation=False,
        )
    if action_type == "pc_write":
        from tempa.pc.tools import run_pc_tool_confirmed

        return run_pc_tool_confirmed("write_file", path=payload.get("path", ""), content=payload.get("content", ""))
    if action_type == "pc_mkdir":
        from tempa.pc.tools import run_pc_tool_confirmed

        return run_pc_tool_confirmed("create_directory", path=payload.get("path", ""))
    if action_type == "pc_delete":
        from tempa.pc.tools import run_pc_tool_confirmed

        return run_pc_tool_confirmed("delete_path", path=payload.get("path", ""))
    if action_type == "file_transfer":
        from tempa.pc.transfer.pairing import activate_transfer

        return await activate_transfer(payload.get("path", ""))
    if action_type == "plan_preview":
        from tempa.agents.graph import run_coordinator_full

        context = dict(payload.get("context") or {})
        context["plan_approved"] = True
        return await run_coordinator_full(payload.get("user_message", ""), context)
    if action_type == "qa_autofix":
        from tempa.qa.fix.autofix import apply_autofix
        from tempa.qa.github.auth import get_installation_token
        from tempa.qa.installations import installation_id_for_repo
        from tempa.qa.store import update_finding

        repo = str(payload.get("repo") or "")
        inst_id = installation_id_for_repo(repo)
        if not inst_id:
            raise RuntimeError(f"No GitHub installation for {repo}")
        token = get_installation_token(inst_id)
        result = apply_autofix({**payload, "token": token})
        finding_id = str(payload.get("finding_id") or "")
        if finding_id:
            update_finding(finding_id, status="fix_applied", github_comment_url=result.get("pr_url"))
        return result
    raise ValueError(f"No executor for action type: {action_type}")
