from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


def test_local_tz_defaults_to_asia_karachi(monkeypatch):
    monkeypatch.delenv("TEMPA_TIMEZONE", raising=False)
    from tempa.core import timezone as tz_mod
    from tempa.settings import get_settings

    get_settings.cache_clear()
    assert tz_mod.local_tz().key == "Asia/Karachi"
    assert tz_mod.tz_name() == "Asia/Karachi"
    get_settings.cache_clear()


def test_local_tz_env_override(monkeypatch):
    monkeypatch.setenv("TEMPA_TIMEZONE", "Europe/London")
    from tempa.core import timezone as tz_mod

    assert tz_mod.local_tz().key == "Europe/London"
    monkeypatch.delenv("TEMPA_TIMEZONE", raising=False)


def test_format_local_now_includes_timezone(monkeypatch):
    monkeypatch.setenv("TEMPA_TIMEZONE", "Asia/Karachi")
    from tempa.core.timezone import format_local_now, now_local

    fixed = datetime(2026, 6, 21, 15, 30, tzinfo=ZoneInfo("Asia/Karachi"))
    monkeypatch.setattr("tempa.core.timezone.now_local", lambda: fixed)
    rendered = format_local_now()
    assert "Asia/Karachi" in rendered
    assert "15:30" in rendered


def test_whatsapp_context_uses_configured_timezone(monkeypatch):
    monkeypatch.setenv("TEMPA_TIMEZONE", "Asia/Karachi")
    from tempa.channels.whatsapp.context import _format_timestamp

    ts = _format_timestamp("2026-06-21T10:00:00+00:00")
    assert ts == "15:00"
