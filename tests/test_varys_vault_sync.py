from __future__ import annotations

from pathlib import Path

import pytest

from tempa.rag.ingest import search_memory
from tempa.varys.vault_sync import ensure_vault_initialized, mine_vault, sync_vault_file


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vector = tmp_path / "vector"
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VARYS_VAULT_DIR", str(vault))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield vault
    get_settings.cache_clear()


def test_vault_sync_ingests_wing_metadata(vault_env):
    vault = ensure_vault_initialized()
    project = vault / "projects" / "tempa" / "notes.md"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("Architecture uses FastAPI and Chroma.", encoding="utf-8")
    result = sync_vault_file(project)
    assert result.get("chunks_created", 0) >= 1
    hits = search_memory("FastAPI architecture", wing="tempa", top_k=3)
    assert hits
    meta = hits[0]["metadata"]
    assert meta.get("wing") == "tempa"
    assert meta.get("tool") == "vault"


def test_mine_vault(vault_env):
    vault = ensure_vault_initialized()
    (vault / "memory" / "prefs.md").write_text("Prefer concise replies.", encoding="utf-8")
    stats = mine_vault()
    assert stats["files"] >= 1
    assert stats["chunks_created"] >= 1
