from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from tempa.rag.ingest import ingest_text
from tempa.rag.store import get_store
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)


def _summarize_text(text: str) -> str:
    router = get_router()
    response = router.chat_completion(
        category="text",
        messages=[
            {
                "role": "user",
                "content": (
                    "Summarize the following into one paragraph with key facts and action items:\n\n"
                    f"{text[:8000]}"
                ),
            }
        ],
        max_tokens=384,
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def _recent_chunks(*, hours: int = 24, limit: int = 200) -> list[dict[str, Any]]:
    store = get_store()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        result = store.collection.get(
            include=["documents", "metadatas"],
            limit=limit,
        )
    except Exception:
        logger.debug("Consolidation chunk fetch failed", exc_info=True)
        return []

    chunks: list[dict[str, Any]] = []
    for doc, meta, doc_id in zip(
        result.get("documents") or [],
        result.get("metadatas") or [],
        result.get("ids") or [],
    ):
        if not doc or not meta:
            continue
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        if "semantic" in tags or "consolidation" in tags:
            continue
        ts = str(meta.get("timestamp") or "")
        if ts and ts < cutoff:
            continue
        chunks.append({"id": doc_id, "content": doc, "metadata": meta})
    return chunks


def run_consolidation(*, hours: int = 24) -> dict[str, Any]:
    """Consolidate recent episodic chunks into semantic summaries grouped by tool/source."""
    chunks = _recent_chunks(hours=hours)
    if not chunks:
        return {"groups": 0, "summaries_written": 0}

    groups: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        meta = chunk["metadata"]
        key = f"{meta.get('tool', 'unknown')}:{meta.get('source', 'unknown')}"
        groups[key].append(chunk["content"])

    written = 0
    for key, texts in groups.items():
        combined = "\n".join(texts[:20])
        if len(combined.split()) < 40:
            continue
        try:
            summary = _summarize_text(combined)
        except Exception:
            logger.debug("Consolidation summary failed for %s", key, exc_info=True)
            continue
        if not summary:
            continue
        tool, _, source = key.partition(":")
        ingest_text(
            summary,
            tool=tool,
            source=f"{source}:consolidation",
            tags=["semantic", "consolidation"],
        )
        written += 1

    logger.info("Memory consolidation: %s groups, %s summaries written", len(groups), written)
    return {"groups": len(groups), "summaries_written": written}
