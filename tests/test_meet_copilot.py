"""Tests for Meet copilot suggestion heuristics."""

from __future__ import annotations

from tempa.meet.copilot import _looks_like_question


def test_looks_like_question_detects_direct_questions():
    assert _looks_like_question("What do you think about the timeline?")
    assert _looks_like_question("Can you share an update?")
    assert _looks_like_question("Status on the API?")


def test_looks_like_question_ignores_statements():
    assert not _looks_like_question("We will ship on Friday")
    assert not _looks_like_question("")
