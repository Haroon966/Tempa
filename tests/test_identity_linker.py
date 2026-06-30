from __future__ import annotations

from unittest.mock import patch

import pytest

from tempa.channels.contacts.linker import link_identities, resolve_slack_to_jira
from tempa.channels.contacts.store import init_contacts_db, upsert_contacts


@pytest.fixture
async def contacts_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    await init_contacts_db()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_link_identities_merges_by_email(contacts_env):
    await upsert_contacts(
        [
            {"id": "slack:U123", "name": "Haroon Ali", "email": "haroon@company.com", "source": "slack"},
            {"id": "jira:abc123", "name": "Haroon Ali", "email": "haroon@company.com", "source": "jira"},
            {"id": "gmail:haroon@company.com", "name": "Haroon", "email": "haroon@company.com", "source": "gmail"},
        ]
    )
    result = link_identities()
    assert result["status"] == "ok"
    assert result["identity_link_count"] == 1

    resolved = resolve_slack_to_jira("U123")
    assert resolved is not None
    assert resolved["account_id"] == "abc123"
    assert resolved["source"] == "link"
