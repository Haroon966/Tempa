"""Permanent Slack participants + profile cache for Sessions."""

from __future__ import annotations

import json
from pathlib import Path

from tempa.channels.slack import conversation as conv
from tempa.channels.slack import cursor_jobs as jobs
from tempa.channels.slack import profiles as profiles_mod


def test_fetch_one_reads_slack_response_data():
    class FakeResp:
        data = {
            "ok": True,
            "user": {
                "id": "U9",
                "name": "ada",
                "profile": {
                    "display_name": "Ada",
                    "image_72": "https://cdn.example/a.png",
                },
            },
        }

    class FakeClient:
        def users_info(self, user):
            assert user == "U9"
            return FakeResp()

    row = profiles_mod._fetch_one(FakeClient(), "U9")
    assert row == {"name": "Ada", "image": "https://cdn.example/a.png"}


def test_enqueue_seeds_participant_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: type("S", (), {"tempa_data_dir": tmp_path})(),
    )
    jid = jobs.enqueue_cursor_job(
        {"channel_id": "C1", "thread_ts": "1.1", "user_id": "U1", "ask_text": "hi"}
    )
    row = jobs.get_job(jid)
    assert row is not None
    assert row["participant_ids"] == ["U1"]


def test_add_thread_participants_persists_multi_user(tmp_path, monkeypatch):
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: type("S", (), {"tempa_data_dir": tmp_path})(),
    )
    jid = jobs.enqueue_cursor_job(
        {"channel_id": "C1", "thread_ts": "1.1", "user_id": "U1"}
    )
    n = jobs.add_thread_participants(channel_id="C1", thread_ts="1.1", user_ids=["U2", "U1"])
    assert n == 1
    row = jobs.get_job(jid)
    assert row is not None
    # Starter stays first
    assert row["participant_ids"] == ["U1", "U2"]
    # Idempotent
    assert jobs.add_thread_participants(channel_id="C1", thread_ts="1.1", user_ids=["U2"]) == 0


def test_record_turn_updates_job_participants(tmp_path, monkeypatch):
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: type("S", (), {"tempa_data_dir": tmp_path})(),
    )
    monkeypatch.setattr(
        conv,
        "get_settings",
        lambda: type("S", (), {"sessions_dir": tmp_path / "sessions"})(),
    )
    monkeypatch.setattr(profiles_mod, "remember_profile", lambda _uid: None)
    jid = jobs.enqueue_cursor_job(
        {"channel_id": "C1", "thread_ts": "1.1", "user_id": "U1"}
    )
    conv.record_conversation_turn(
        role="user",
        text="second person joins",
        user_id="U2",
        channel_id="C1",
        thread_ts="1.1",
        conversation_key="1.1",
    )
    row = jobs.get_job(jid)
    assert row is not None
    assert row["participant_ids"] == ["U1", "U2"]


def test_enrich_jobs_uses_persisted_participant_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(
        profiles_mod,
        "get_settings",
        lambda: type("S", (), {"sessions_dir": tmp_path / "sessions"})(),
    )
    monkeypatch.setattr(
        profiles_mod,
        "resolve_profiles",
        lambda ids: {
            "U1": {"name": "Haroon Ali", "image": "https://cdn.example/h.png"},
            "U2": {"name": "Ali Ahmed", "image": "https://cdn.example/a.png"},
        },
    )
    monkeypatch.setattr(profiles_mod, "backfill_participant_ids", lambda _jobs: None)

    jobs_out = profiles_mod.enrich_jobs(
        [
            {
                "id": "j1",
                "user_id": "U1",
                "channel_id": "C1",
                "thread_ts": "1.1",
                "participant_ids": ["U1", "U2"],
            }
        ]
    )
    names = [p["name"] for p in jobs_out[0]["participants"]]
    assert names == ["Haroon Ali", "Ali Ahmed"]
    assert jobs_out[0]["user_name"] == "Haroon Ali"


def test_participants_for_threads_collects_unique_humans(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions" / "slack"
    sessions.mkdir(parents=True)
    path = sessions / "conversation.jsonl"
    rows = [
        {"role": "user", "user_id": "U1", "channel_id": "C1", "thread_ts": "1.1", "text": "a"},
        {"role": "assistant", "user_id": "BOT", "channel_id": "C1", "thread_ts": "1.1", "text": "b"},
        {"role": "user", "user_id": "U2", "channel_id": "C1", "thread_ts": "1.1", "text": "c"},
        {"role": "user", "user_id": "U1", "channel_id": "C1", "thread_ts": "1.1", "text": "d"},
        {"role": "user", "user_id": "U9", "channel_id": "C2", "thread_ts": "2.2", "text": "e"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        conv,
        "get_settings",
        lambda: type("S", (), {"sessions_dir": tmp_path / "sessions"})(),
    )

    got = conv.participants_for_threads([("C1", "1.1"), ("C2", "2.2")])
    assert got["C1:1.1"] == ["U1", "U2"]
    assert got["C2:2.2"] == ["U9"]


def test_backfill_writes_participant_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: type("S", (), {"tempa_data_dir": tmp_path})(),
    )
    monkeypatch.setattr(
        conv,
        "get_settings",
        lambda: type("S", (), {"sessions_dir": tmp_path / "sessions"})(),
    )
    sessions = tmp_path / "sessions" / "slack"
    sessions.mkdir(parents=True)
    (sessions / "conversation.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"role": "user", "user_id": "U1", "channel_id": "C1", "thread_ts": "1.1", "text": "a"},
                {"role": "user", "user_id": "U2", "channel_id": "C1", "thread_ts": "1.1", "text": "b"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    jid = jobs.enqueue_cursor_job(
        {"channel_id": "C1", "thread_ts": "1.1", "user_id": "U1"}
    )
    # Simulate legacy job without multi-user ids beyond starter
    jobs.update_job(jid, participant_ids=["U1"])
    # Clear multi so backfill path for "missing second user" — actually backfill only
    # runs when participant_ids is empty. Clear it.
    jobs.update_job(jid, participant_ids=[])
    row = jobs.get_job(jid)
    assert row is not None
    profiles_mod.backfill_participant_ids([row])
    saved = jobs.get_job(jid)
    assert saved is not None
    assert saved["participant_ids"] == ["U1", "U2"]
