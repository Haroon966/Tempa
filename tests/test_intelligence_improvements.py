from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_procedural_memory_add_list_delete(tmp_path, monkeypatch):
    from tempa.rag import procedural

    monkeypatch.setattr(procedural, "_store_path", lambda: tmp_path / "memory" / "procedural.json")
    monkeypatch.setattr(
        "tempa.rag.procedural.ingest_text",
        lambda *args, **kwargs: {"chunks_created": 0},
    )

    record = procedural.add_preference("Always send minutes to WhatsApp group X", source="test")
    assert record["rule"].startswith("Always")
    prefs = procedural.list_preferences()
    assert len(prefs) == 1

    captured = procedural.extract_preference_from_message("From now on use formal tone for client emails")
    assert captured is not None

    assert procedural.delete_preference(record["id"]) is True
    assert procedural.list_preferences() == []


def test_compute_execution_waves_parallel_when_no_deps():
    from tempa.agents.graph import compute_execution_waves

    subtasks = [
        {"agent": "calendar", "task": "a", "depends_on": []},
        {"agent": "rag", "task": "b", "depends_on": []},
    ]
    waves = compute_execution_waves(subtasks)
    assert len(waves) == 1
    assert len(waves[0]) == 2


def test_search_memory_metadata_filters(monkeypatch):
    from tempa.rag.ingest import search_memory

    class FakeCollection:
        def query(self, **kwargs):
            return {
                "documents": [["doc1", "doc2"]],
                "metadatas": [
                    [
                        {
                            "tool": "meet",
                            "source": "m1",
                            "timestamp": "2026-06-01T10:00:00+00:00",
                            "participant": "alice@co.com",
                            "tags": "minutes",
                        },
                        {
                            "tool": "whatsapp",
                            "source": "w1",
                            "timestamp": "2026-06-15T10:00:00+00:00",
                            "participant": "+123",
                            "tags": "chat",
                        },
                    ]
                ],
                "distances": [[0.1, 0.2]],
                "ids": [["id1", "id2"]],
            }

    class FakeStore:
        collection = FakeCollection()

    class FakeEmbedder:
        def embed(self, text):
            return [0.1, 0.2]

    monkeypatch.setattr("tempa.rag.ingest.get_store", lambda: FakeStore())
    monkeypatch.setattr("tempa.rag.ingest.get_embedder", lambda: FakeEmbedder())

    results = search_memory(
        "meet minutes",
        top_k=5,
        tool="meet",
        date_from="2026-06-01T00:00:00+00:00",
        date_to="2026-06-10T00:00:00+00:00",
        participant="alice",
        tags=["minutes"],
    )
    assert len(results) == 1
    assert results[0]["metadata"]["tool"] == "meet"


def test_builtin_plugin_tools_registered(monkeypatch):
    from tempa.plugins.registry import _REGISTRY, list_tools, load_builtin_plugins

    monkeypatch.setattr("tempa.plugins.registry.get_plugin_store", lambda: object())
    _REGISTRY.clear()
    load_builtin_plugins()
    names = {t["name"] for t in list_tools()}
    assert "memory.search" in names
    assert "gmail.search" in names
    assert "calendar.list_events" in names
    assert "meet.join" in names
    assert "pc.run_shell" in names


def test_extract_filters_from_query_heuristic():
    from tempa.rag.filters import extract_filters_from_query

    filters = extract_filters_from_query("What did we decide in the meet last Tuesday?")
    assert filters.get("tool") == "meet"
    assert filters.get("date_from")
