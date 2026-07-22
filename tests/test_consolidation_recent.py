from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from tempa.rag.consolidation import _recent_chunks


def test_recent_chunks_orders_by_timestamp_desc():
    now = datetime.now(timezone.utc)
    older = (now - timedelta(hours=2)).isoformat()
    newer = (now - timedelta(minutes=5)).isoformat()
    ancient = (now - timedelta(hours=48)).isoformat()

    store = MagicMock()
    store.collection.get.return_value = {
        "documents": ["old doc", "new doc", "ancient", "mid"],
        "metadatas": [
            {"timestamp": older, "tags": ["episodic"]},
            {"timestamp": newer, "tags": ["episodic"]},
            {"timestamp": ancient, "tags": ["episodic"]},
            {"timestamp": older, "tags": ["semantic"]},
        ],
        "ids": ["1", "2", "3", "4"],
    }

    with patch("tempa.rag.consolidation.get_store", return_value=store):
        chunks = _recent_chunks(hours=24, limit=10)

    assert [c["id"] for c in chunks] == ["2", "1"]
    assert chunks[0]["content"] == "new doc"
