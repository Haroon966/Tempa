from __future__ import annotations

import json
from pathlib import Path

import pytest

from tempa.core import chat_sessions as cs


@pytest.fixture
def chat_store(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    monkeypatch.setattr(cs, "_chat_dir", lambda: sessions / "chat")
    (sessions / "chat").mkdir(parents=True, exist_ok=True)
    return sessions / "chat"


def test_create_and_list_sessions(chat_store):
    s1 = cs.create_session()
    s2 = cs.create_session(title="Custom title")
    listed = cs.list_sessions()
    assert len(listed) == 2
    assert listed[0]["id"] in {s1["id"], s2["id"]}
    assert s2["title"] == "Custom title"


def test_append_message_and_auto_title(chat_store):
    session = cs.create_session()
    cs.append_message(session["id"], "user", "What meetings do I have tomorrow?")
    updated = cs.get_session(session["id"])
    assert updated is not None
    assert len(updated["messages"]) == 1
    assert updated["title"].startswith("What meetings")
    cs.append_message(session["id"], "assistant", "You have two meetings.", sources=[{"label": "calendar"}])
    updated = cs.get_session(session["id"])
    assert len(updated["messages"]) == 2
    assert updated["messages"][1]["sources"][0]["label"] == "calendar"


def test_delete_session(chat_store):
    session = cs.create_session()
    assert cs.delete_session(session["id"]) is True
    assert cs.get_session(session["id"]) is None
    assert cs.list_sessions() == []
    assert cs.delete_session("missing") is False


def test_ensure_session_creates_when_missing(chat_store):
    session = cs.ensure_session(None)
    assert session["id"]
    again = cs.ensure_session(session["id"])
    assert again["id"] == session["id"]


def test_session_count(chat_store):
    assert cs.session_count() == 0
    cs.create_session()
    cs.create_session()
    assert cs.session_count() == 2
