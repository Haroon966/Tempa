from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tempa.settings import get_settings

_handler: Any = None
_last_event_at: str | None = None
_last_error: str | None = None
_seen_event_ids: set[str] = set()


def set_handler(handler: Any) -> None:
    global _handler
    _handler = handler


def get_handler() -> Any:
    return _handler


def mark_event_seen(event_id: str) -> bool:
    """Return True if this event_id is new."""
    if not event_id:
        return True
    if event_id in _seen_event_ids:
        return False
    _seen_event_ids.add(event_id)
    if len(_seen_event_ids) > 500:
        drop = list(_seen_event_ids)[:100]
        for item in drop:
            _seen_event_ids.discard(item)
    return True


def touch_event() -> None:
    global _last_event_at
    _last_event_at = datetime.now(timezone.utc).isoformat()


def set_error(message: str | None) -> None:
    global _last_error
    _last_error = message


def slack_configured() -> bool:
    settings = get_settings()
    return bool(settings.slack_bot_token.strip() and settings.slack_app_token.strip())


async def connection_status() -> dict[str, Any]:
    settings = get_settings()
    configured = slack_configured()
    owner_configured = bool(settings.slack_owner_user_id.strip())
    connected = False
    handler = get_handler()
    if handler is not None and handler.client is not None:
        try:
            connected = await handler.client.is_connected()
        except Exception:
            connected = False
    status = "disconnected"
    if not configured:
        status = "disconnected"
        detail = "Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env"
    elif connected:
        status = "connected"
        detail = None
    elif _last_error:
        status = "error"
        detail = _last_error
    else:
        status = "connecting"
        detail = "Socket Mode starting"
    return {
        "connected": connected,
        "configured": configured,
        "owner_configured": owner_configured,
        "status": status,
        "detail": detail,
        "last_event_at": _last_event_at,
        "owner_user_id": settings.slack_owner_user_id or None,
    }
