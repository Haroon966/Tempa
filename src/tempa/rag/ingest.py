from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from tempa.rag.embeddings import get_embedder
from tempa.rag.hybrid import _bm25_score, reciprocal_rank_fusion
from tempa.rag.store import get_store

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


def _create_chunks(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[dict[str, Any]]:
    """Split text into overlapping chunks (character-based approximation)."""
    words = text.split()
    if not words:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    chunk_id = 0
    while start < len(words):
        end = min(len(words), start + chunk_size)
        chunk_text = " ".join(words[start:end])
        if chunk_text.strip():
            chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": chunk_text,
                    "start": start,
                    "end": end,
                    "length": len(chunk_text),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            chunk_id += 1
        if end >= len(words):
            break
        start = max(0, end - chunk_overlap)
    return chunks


def ingest_text(
    text: str,
    *,
    tool: str,
    source: str,
    participants: list[str] | None = None,
    tags: list[str] | None = None,
    meet_link: str | None = None,
    title: str = "",
) -> dict[str, Any]:
    """Upsert text chunks into unified Chroma with PRD metadata schema."""
    if not text.strip():
        return {"chunks_created": 0, "total_chunks": get_store().count()}

    chunks = _create_chunks(text)
    embedder = get_embedder()
    store = get_store()
    timestamp = datetime.now(timezone.utc).isoformat()

    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []

    participant = (participants[0] if participants else "") or source

    for chunk in chunks:
        chunk_hash = hashlib.sha256(chunk["text"].encode()).hexdigest()[:16]
        doc_id = f"{tool}:{source}:{chunk_hash}"
        documents.append(chunk["text"])
        embeddings.append(embedder.embed(chunk["text"]))
        metadatas.append(
            {
                "tool": tool,
                "source": source,
                "participant": participant,
                "timestamp": timestamp,
                "participants": ",".join(participants or []),
                "tags": ",".join(tags or []),
                "meet_link": meet_link or "",
                "title": title,
                "chunk_start": chunk["start"],
                "chunk_end": chunk["end"],
            }
        )
        ids.append(doc_id)

    try:
        store.collection.upsert(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("RAG ingest upsert failed (non-fatal): %s", exc)
        return {"chunks_created": 0, "total_chunks": 0, "chunk_ids": [], "ingest_error": str(exc)}

    from tempa.rag.semantic import maybe_write_semantic_summary

    maybe_write_semantic_summary(text, tool=tool, source=source)
    return {"chunks_created": len(chunks), "total_chunks": store.count(), "chunk_ids": ids}


def _passes_metadata_filters(
    metadata: dict[str, Any],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    participant: str | None = None,
    tags: list[str] | None = None,
) -> bool:
    ts = str(metadata.get("timestamp") or "")
    if date_from and ts and ts < date_from:
        return False
    if date_to and ts and ts > date_to:
        return False
    if participant:
        needle = participant.lower()
        hay = " ".join(
            [
                str(metadata.get("participant") or ""),
                str(metadata.get("participants") or ""),
                str(metadata.get("source") or ""),
            ]
        ).lower()
        if needle not in hay:
            return False
    if tags:
        meta_tags = str(metadata.get("tags") or "").lower()
        if not any(tag.lower() in meta_tags for tag in tags):
            return False
    return True


def search_memory(
    query: str,
    *,
    top_k: int = 5,
    tool: str | None = None,
    meet_link: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    participant: str | None = None,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    embedder = get_embedder()
    store = get_store()
    where: dict[str, Any] | None = None
    filters: list[dict[str, Any]] = []
    if tool:
        filters.append({"tool": tool})
    if meet_link:
        filters.append({"meet_link": meet_link})
    if len(filters) == 1:
        where = filters[0]
    elif len(filters) > 1:
        where = {"$and": filters}

    results = store.collection.query(
        query_embeddings=[embedder.embed(query)],
        n_results=max(top_k * 4, 20),
        include=["documents", "metadatas", "distances"],
        where=where,
    )

    formatted: list[dict[str, Any]] = []
    if not results["documents"] or not results["documents"][0]:
        return formatted

    vector_ranked: list[str] = []
    doc_by_id: dict[str, dict[str, Any]] = {}
    for doc, metadata, distance, doc_id in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
        results["ids"][0],
    ):
        if not _passes_metadata_filters(
            metadata,
            date_from=date_from,
            date_to=date_to,
            participant=participant,
            tags=tags,
        ):
            continue
        vector_ranked.append(doc_id)
        doc_by_id[doc_id] = {
            "content": doc,
            "metadata": metadata,
            "vector_score": 1.0 - float(distance),
        }

    bm25_ranked = sorted(
        doc_by_id.keys(),
        key=lambda did: _bm25_score(query, doc_by_id[did]["content"]),
        reverse=True,
    )
    fused = reciprocal_rank_fusion([vector_ranked, bm25_ranked])[:top_k]

    for doc_id, rrf_score in fused:
        row = doc_by_id[doc_id]
        formatted.append(
            {
                "content": row["content"],
                "score": rrf_score,
                "metadata": row["metadata"],
            }
        )
    return formatted
