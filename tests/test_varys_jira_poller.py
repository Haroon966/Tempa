from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tempa.varys import harness
from tempa.varys.pollers import poll_jira_issues


@pytest.fixture
def harness_db(tmp_path, monkeypatch):
    db_path = tmp_path / "harness.db"
    monkeypatch.setenv("VARYS_HARNESS_DB", str(db_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_poll_jira_issues_enqueues_events(harness_db, monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "dev@acme.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("JIRA_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    issues = [
        {
            "key": "ENG-7",
            "summary": "Fix OAuth",
            "status": "In Progress",
            "assignee": "Dev",
            "project": "ENG",
            "updated": "2026-06-26T11:00:00.000+0000",
            "url": "https://acme.atlassian.net/browse/ENG-7",
        }
    ]
    with patch("tempa.varys.pollers.jira_poller.poll_repos", return_value=issues):
        count = poll_jira_issues()

    assert count == 1
    db = harness.get_db()
    try:
        row = db.execute("SELECT type, source, payload FROM events WHERE source='jira'").fetchone()
        assert row[0] == "jira.issue_updated"
        assert row[1] == "jira"
        payload = json.loads(row[2])
        assert payload["key"] == "ENG-7"
    finally:
        db.close()
    get_settings.cache_clear()


def test_poll_jira_issues_skips_when_disabled(harness_db, monkeypatch):
    monkeypatch.setenv("JIRA_ENABLED", "false")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    assert poll_jira_issues() == 0
    get_settings.cache_clear()
