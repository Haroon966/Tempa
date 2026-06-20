from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from tempa.settings import get_settings

COLLECTION_NAME = "tempa_unified"
logger = logging.getLogger(__name__)


class UnifiedVectorStore:
    """Single Chroma collection for all Tempa memory."""

    def __init__(self) -> None:
        settings = get_settings()
        settings.vector_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(settings.vector_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self):
        return self._collection

    def count(self) -> int:
        try:
            return self._collection.count()
        except Exception:
            return 0


_store: UnifiedVectorStore | None = None


def ensure_store_healthy(*, reset_on_failure: bool = False) -> bool:
    """Verify ChromaDB is readable; optionally reset corrupted store."""
    global _store
    settings = get_settings()
    try:
        store = get_store()
        store._collection.peek(limit=1)
        return True
    except Exception as exc:
        logger.warning("ChromaDB health check failed: %s", exc)
        if not reset_on_failure:
            return False
        backup = settings.vector_dir.with_name(
            f"vector.bak.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        )
        try:
            if settings.vector_dir.exists():
                shutil.move(str(settings.vector_dir), str(backup))
            settings.vector_dir.mkdir(parents=True, exist_ok=True)
            _store = None
            get_store()._collection.peek(limit=1)
            logger.warning("ChromaDB reset; backup at %s", backup)
            return True
        except Exception as reset_exc:
            logger.exception("ChromaDB reset failed: %s", reset_exc)
            return False


def get_store() -> UnifiedVectorStore:
    global _store
    if _store is None:
        _store = UnifiedVectorStore()
    return _store
