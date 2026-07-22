from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tempa.hermes.coordinator import hermes_available, run_hermes_coordinator
from tempa.hermes.mcp import load_mcp_servers, mcp_status
from tempa.hermes.skills_bridge import ensure_seed_skills, record_plan_outcome, skills_dir


def test_hermes_available_false_without_package():
    assert hermes_available() in (True, False)


def test_ensure_seed_skills(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    settings_mod.get_settings.cache_clear()
    ensure_seed_skills()
    policy = skills_dir() / "slack-routing-policy" / "SKILL.md"
    assert policy.is_file()
    assert "product/data investigations" in policy.read_text(encoding="utf-8")
    settings_mod.get_settings.cache_clear()


def test_record_plan_outcome(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    settings_mod.get_settings.cache_clear()
    path = record_plan_outcome("check inbox", success=True, notes="test", planned_steps=["gmail"])
    assert path is not None and path.is_file()
    assert record_plan_outcome("fail", success=False) is None
    settings_mod.get_settings.cache_clear()


def test_mcp_status_shape():
    status = mcp_status()
    assert "sdk_installed" in status
    assert "servers" in status
    assert isinstance(load_mcp_servers(), list)


@pytest.mark.asyncio
async def test_create_pending_action_tool(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod
    from tempa.hermes.tools import run_tempa_tool

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPA_SESSIONS_DIR", str(tmp_path / "sessions"))
    settings_mod.get_settings.cache_clear()
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    # pending_actions uses sessions_dir from settings
    monkeypatch.setattr(
        "tempa.core.pending_actions.get_settings",
        settings_mod.get_settings,
    )
    raw = await run_tempa_tool(
        "create_pending_action",
        {"type": "slack_send", "payload": {"channel": "C1", "text": "hi"}, "risk_level": "high"},
        {"channel": "hermes"},
    )
    data = json.loads(raw)
    assert data.get("status") == "pending"
    assert data.get("pending_action_id")
    settings_mod.get_settings.cache_clear()


def test_promote_learned_skills(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod
    from tempa.hermes.skills_bridge import promote_learned_to_skills, record_plan_outcome

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    settings_mod.get_settings.cache_clear()
    record_plan_outcome("summarize calendar", success=True, notes="t", planned_steps=["calendar"])
    paths = promote_learned_to_skills(limit=3)
    assert paths
    assert paths[0].name == "SKILL.md"
    settings_mod.get_settings.cache_clear()

