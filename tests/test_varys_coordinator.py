from __future__ import annotations

import pytest

from tempa.agents.graph import _should_use_varys


def test_should_use_varys_modes(monkeypatch):
    from tempa.settings import get_settings

    monkeypatch.setenv("TEMPA_COORDINATOR", "langgraph")
    get_settings.cache_clear()
    assert _should_use_varys("fix the bug", {}) is False

    monkeypatch.setenv("TEMPA_COORDINATOR", "varys")
    get_settings.cache_clear()
    assert _should_use_varys("hello", {}) is True

    monkeypatch.setenv("TEMPA_COORDINATOR", "hybrid")
    get_settings.cache_clear()
    assert _should_use_varys("fix login in repo", {}) is True
    assert _should_use_varys("what meetings today", {}) is False
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_varys_coordinator_work_request(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_COORDINATOR", "varys")
    monkeypatch.setenv("VARYS_HARNESS_DB", str(tmp_path / "harness.db"))
    monkeypatch.setenv("VARYS_VAULT_DIR", str(tmp_path / "vault"))
    from tempa.settings import get_settings

    get_settings.cache_clear()

    from tempa.varys.coordinator import run_varys_coordinator

    result = await run_varys_coordinator("fix oauth redirect in tempa", {"channel": "dashboard"})
    assert result["paused"] is True
    assert result["pending_actions"]
    assert "ticket" in result["response"].lower()
    get_settings.cache_clear()
