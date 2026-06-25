from __future__ import annotations

import logging

from tempa.rag.store import COLLECTION_NAME, get_store

logger = logging.getLogger(__name__)


def purge_by_source(source: str) -> int:
    store = get_store()
    try:
        existing = store.collection.get(where={"source": source}, include=[])
        ids = existing.get("ids") or []
        if ids:
            store.collection.delete(ids=ids)
        return len(ids)
    except Exception:
        logger.debug("purge_by_source failed for %s", source, exc_info=True)
        return 0


def purge_gmail_message(message_id: str) -> int:
    return purge_by_source(message_id)


def purge_calendar_event(event_id: str) -> int:
    return purge_by_source(event_id)


def purge_meeting_vectors(meeting_id: str) -> int:
    removed = 0
    for src in (meeting_id, f"{meeting_id}:minutes"):
        removed += purge_by_source(src)
    try:
        store = get_store()
        existing = store.collection.get(where={"meet_link": {"$ne": ""}}, include=["metadatas"])
        ids_to_delete: list[str] = []
        for doc_id, meta in zip(existing.get("ids") or [], existing.get("metadatas") or []):
            if meta and meta.get("source", "").startswith(meeting_id):
                ids_to_delete.append(doc_id)
        if ids_to_delete:
            store.collection.delete(ids=ids_to_delete)
            removed += len(ids_to_delete)
    except Exception:
        pass
    return removed


def purge_all_vectors() -> None:
    store = get_store()
    try:
        store._client.delete_collection(COLLECTION_NAME)
        store._collection = store._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception:
        logger.exception("Failed to purge vector collection")
