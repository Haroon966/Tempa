from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tempa.learning.curator import run_curator
from tempa.learning.loop import after_turn
from tempa.learning.store import (
    is_immutable,
    record_skill_usage,
    write_skill_md,
)
from tempa.skills.loader import load_all_skills, reload_skills


def test_write_and_load_auto_skill(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    settings_mod.get_settings.cache_clear()
    path = write_skill_md(
        "inbox-triage",
        description="Triage urgent mail",
        triggers=["urgent inbox", "triage mail"],
        workers=["gmail"],
        body="1. Search unread\n2. Summarize urgent",
    )
    assert path.is_file()
    reload_skills()
    names = {s.name for s in load_all_skills()}
    assert "inbox-triage" in names
    settings_mod.get_settings.cache_clear()


def test_immutable_policy():
    assert is_immutable("slack-routing-policy") is True


@pytest.mark.asyncio
async def test_after_turn_creates_skill_via_llm(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    settings_mod.get_settings.cache_clear()

    fake = {
        "should_create": True,
        "name": "cal-and-mail",
        "description": "Check calendar and inbox",
        "triggers": ["calendar and inbox", "mail and schedule"],
        "workers": ["gmail", "calendar"],
        "body": "Check gmail then calendar.",
    }
    with patch("tempa.learning.loop.llm_json", return_value=fake):
        with patch("tempa.learning.loop._maybe_refine_skills", return_value=[]):
            with patch("tempa.learning.loop._memory_nudge", return_value=0):
                out = await after_turn(
                    "check my calendar and inbox",
                    success=True,
                    planned_steps=[{"agent": "gmail"}, {"agent": "calendar"}],
                    response="Here is a summary",
                    notes="test",
                )
    assert out.get("created_skill") == "cal-and-mail"
    assert (tmp_path / "skills" / "auto" / "cal-and-mail" / "SKILL.md").is_file()
    settings_mod.get_settings.cache_clear()


def test_curator_archives_failing_skill(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    settings_mod.get_settings.cache_clear()
    write_skill_md(
        "flaky",
        description="flaky",
        triggers=["flaky thing"],
        workers=["plugin"],
        body="do x",
    )
    for _ in range(5):
        record_skill_usage(["flaky"], success=False)
    result = run_curator()
    assert "flaky" in result["archived"]
    assert not (tmp_path / "skills" / "auto" / "flaky" / "SKILL.md").exists()
    settings_mod.get_settings.cache_clear()
