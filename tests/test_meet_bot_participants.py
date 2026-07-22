"""Tests for meeting-bot vs human participant classification."""

from __future__ import annotations

from tempa.meet.bot_participants import clear_bot_cache, count_humans, is_meeting_bot


def setup_function() -> None:
    clear_bot_cache()


def test_known_bots_classified():
    assert is_meeting_bot("Rumi")
    assert is_meeting_bot("Notetaker")
    assert is_meeting_bot("Fireflies.ai Notetaker")
    assert is_meeting_bot("OtterPilot")
    assert is_meeting_bot("Tempa")
    assert is_meeting_bot("read.ai")
    assert is_meeting_bot("Granola")


def test_humans_not_classified_as_bots():
    assert not is_meeting_bot("Alice")
    assert not is_meeting_bot("Haroon Ahmed")
    assert not is_meeting_bot("")
    assert not is_meeting_bot(None)


def test_count_humans_ignores_bots():
    names = ["Alice", "Tempa", "Rumi", "Notetaker", "Bob"]
    assert count_humans(names) == 2


def test_count_humans_empty_name_counts_as_human():
    # Safer: stay in call when we cannot read a display name.
    assert count_humans(["", "Tempa"]) == 1
