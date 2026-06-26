from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tempa.varys import harness
from tempa.varys.pollers import poll_github_repos, poll_notion_harness


@pytest.fixture
def harness_db(tmp_path, monkeypatch):
    db_path = tmp_path / "harness.db"
    monkeypatch.setenv("VARYS_HARNESS_DB", str(db_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield db_path
    get_settings.cache_clear()


def test_poll_notion_harness_enqueues_events(harness_db, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_HARNESS_DB_ID", "db-123")
    monkeypatch.setenv("NOTION_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    pages = [
        {
            "id": "page-1",
            "title": "Ship auth fix",
            "status": "In Progress",
            "url": "https://notion.so/page-1",
            "last_edited_time": "2026-06-26T10:00:00.000Z",
        }
    ]
    with patch("tempa.varys.pollers.query_harness_database", return_value=pages):
        count = poll_notion_harness()

    assert count == 1
    db = harness.get_db()
    try:
        events = [(row[0], row[1]) for row in db.execute("SELECT type, source FROM events").fetchall()]
        assert ("notion.page_updated", "notion") in events
    finally:
        db.close()
    get_settings.cache_clear()


def test_poll_notion_harness_repolls_on_edit(harness_db, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_HARNESS_DB_ID", "db-123")
    monkeypatch.setenv("NOTION_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    page_v1 = {
        "id": "page-1",
        "title": "Ship auth fix",
        "status": "In Progress",
        "url": "https://notion.so/page-1",
        "last_edited_time": "2026-06-26T10:00:00.000Z",
    }
    page_v2 = {**page_v1, "last_edited_time": "2026-06-26T12:00:00.000Z"}
    with patch("tempa.varys.pollers.query_harness_database", return_value=[page_v1]):
        assert poll_notion_harness() == 1
    with patch("tempa.varys.pollers.query_harness_database", return_value=[page_v2]):
        assert poll_notion_harness() == 1

    db = harness.get_db()
    try:
        count = db.execute("SELECT COUNT(*) FROM events WHERE type='notion.page_updated'").fetchone()[0]
        assert count == 2
    finally:
        db.close()
    get_settings.cache_clear()


def test_poll_github_repos_enqueues_pr_events(harness_db, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    pulls = [
        {
            "repo": "acme/app",
            "number": 42,
            "title": "Fix login",
            "state": "open",
            "url": "https://github.com/acme/app/pull/42",
            "updated_at": "2026-06-26T11:00:00Z",
            "user": "dev",
        }
    ]
    with patch("tempa.varys.pollers.github_poller.poll_repos", return_value=pulls):
        with patch("tempa.varys.config.load_varys_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(repos=[{"repo": "acme/app"}])
            count = poll_github_repos()

    assert count == 1
    db = harness.get_db()
    try:
        row = db.execute("SELECT type, payload FROM events WHERE source='github'").fetchone()
        assert row[0] == "github.pr_updated"
        payload = json.loads(row[1])
        assert payload["number"] == 42
    finally:
        db.close()
    get_settings.cache_clear()
