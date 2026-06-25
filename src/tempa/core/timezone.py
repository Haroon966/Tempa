from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from tempa.settings import get_settings

_DEFAULT_TZ = "Asia/Karachi"


def _zone_from_name(name: str) -> ZoneInfo | None:
    name = name.strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def local_tz() -> ZoneInfo:
    """Return the user's local timezone (env override, settings, system, then default)."""
    env_tz = os.environ.get("TEMPA_TIMEZONE", "").strip()
    if env_tz:
        resolved = _zone_from_name(env_tz)
        if resolved is not None:
            return resolved
    try:
        settings = get_settings()
        configured = getattr(settings, "tempa_timezone", "") or ""
        resolved = _zone_from_name(configured)
        if resolved is not None:
            return resolved
    except Exception:
        pass
    try:
        aware = datetime.now().astimezone()
        key = getattr(aware.tzinfo, "key", None)
        if isinstance(key, str) and key:
            return ZoneInfo(key)
    except Exception:
        pass
    return ZoneInfo(_DEFAULT_TZ)


def tz_name() -> str:
    tzinfo = local_tz()
    if isinstance(tzinfo, ZoneInfo):
        return tzinfo.key
    return _DEFAULT_TZ


def now_local() -> datetime:
    return datetime.now(local_tz())


def format_local_now(*, include_tz: bool = True) -> str:
    now = now_local()
    formatted = now.strftime("%A %d %b %Y, %H:%M")
    if include_tz:
        return f"{formatted} ({tz_name()})"
    return formatted
