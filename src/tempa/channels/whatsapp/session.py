from __future__ import annotations

import json
from pathlib import Path

from tempa.settings import get_settings

_STATE_PATH = None


def _state_path() -> Path:
    global _STATE_PATH
    if _STATE_PATH is None:
        _STATE_PATH = get_settings().sessions_dir / "whatsapp" / "connection_state.json"
    return _STATE_PATH


def _load() -> dict:
    path = _state_path()
    if not path.exists():
        return {"connected": False, "state": "unknown", "pause_auto_reply": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"connected": False, "state": "unknown", "pause_auto_reply": False}


def _save(data: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_connection_state(state: str) -> dict:
    connected = state.lower() in {"open", "connected"}
    pause = not connected
    prev = _load()
    data = {
        "connected": connected,
        "state": state,
        "pause_auto_reply": pause,
        "needs_qr_rescan": not connected,
    }
    if connected:
        data["qr_code"] = None
    elif prev.get("qr_code"):
        data["qr_code"] = prev["qr_code"]
    _save(data)
    return data


def store_qr_code(qr: str | None) -> None:
    if qr and len(qr) < 500:
        return
    data = _load()
    if qr:
        data["qr_code"] = qr
    else:
        data.pop("qr_code", None)
    _save(data)


def get_qr_code() -> str | None:
    qr = _load().get("qr_code")
    return qr if isinstance(qr, str) and qr else None


def clear_qr_code() -> None:
    data = _load()
    if "qr_code" in data:
        data.pop("qr_code")
        _save(data)


def is_auto_reply_paused() -> bool:
    return bool(_load().get("pause_auto_reply"))


def needs_qr_rescan() -> bool:
    return bool(_load().get("needs_qr_rescan"))


def get_connection_snapshot() -> dict:
    data = _load()
    try:
        from tempa.channels.whatsapp.qr_tasks import last_qr_error

        err = last_qr_error()
        if err:
            data = {**data, "last_error": err}
    except Exception:
        pass
    return data


def parse_bridge_state(data: dict) -> tuple[str, bool]:
    """Normalize WhatsApp bridge connectionState payload."""
    state = data.get("state")
    if state is None:
        instance = data.get("instance")
        if isinstance(instance, dict):
            state = instance.get("state")
    state_str = str(state or "disconnected")
    connected = state_str.lower() in {"open", "connected"}
    return state_str, connected


def mark_disconnected() -> dict:
    clear_qr_code()
    return update_connection_state("close")


async def sync_connection_from_bridge() -> dict:
    """Refresh local session state from WhatsApp bridge (source of truth)."""
    from tempa.channels.whatsapp.client import WhatsAppBridgeClient

    try:
        client = WhatsAppBridgeClient()
        state_name, _connected = await client.resolved_connection_state()
        return update_connection_state(state_name)
    except Exception:
        return get_connection_snapshot()
