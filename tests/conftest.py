import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tempa.api.app import create_app


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("TEMPA_DATA_DIR", str(data))
    monkeypatch.setenv("VECTOR_DB", "chroma")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_dirs()
    from tempa.channels.contacts.store import init_contacts_db

    asyncio.run(init_contacts_db())


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c
