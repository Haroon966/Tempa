from __future__ import annotations

from pathlib import Path

from tempa.hermes.goals import (
    add_kanban_card,
    create_goal,
    list_goals,
    list_kanban,
    move_kanban_card,
    open_goals_prompt_block,
    update_goal,
)


def test_goals_and_kanban(tmp_path: Path, monkeypatch):
    from tempa import settings as settings_mod

    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    settings_mod.get_settings.cache_clear()

    goal = create_goal("Daily inbox triage", prompt="Summarize urgent mail")
    assert goal["status"] == "open"
    assert list_goals(status="open")
    assert "Standing goals" in open_goals_prompt_block()

    board = list_kanban()
    assert any(c.get("goal_id") == goal["id"] for c in board["doing"])

    updated = update_goal(goal["id"], status="done")
    assert updated and updated["status"] == "done"

    card = add_kanban_card("Follow up", column="backlog")
    moved = move_kanban_card(card["id"], "done")
    assert moved is not None
    assert any(c["id"] == card["id"] for c in list_kanban()["done"])

    settings_mod.get_settings.cache_clear()
