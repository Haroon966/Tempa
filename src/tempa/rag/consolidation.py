from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from tempa.rag.ingest import ingest_text
from tempa.rag.store import get_store
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")


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


def _extract_knowledge_items(text: str) -> list[dict[str, str]]:
    """Extract typed durable knowledge bullets from consolidated text."""
    router = get_router()
    response = router.chat_completion(
        category="text",
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract durable org knowledge from this text. Skip chatter and one-off noise. "
                    'Return JSON only: {"items":[{"kind":"person"|"project"|"decision"|"fact","text":"..."}]}. '
                    "Max 8 items. Empty list if nothing durable.\n\n"
                    f"{text[:8000]}"
                ),
            }
        ],
        max_tokens=512,
        temperature=0.1,
    )
    raw = (response.choices[0].message.content or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "fact").lower()
        body = str(item.get("text") or "").strip()
        if not body:
            continue
        if kind not in ("person", "project", "decision", "fact"):
            kind = "fact"
        out.append({"kind": kind, "text": body})
    return out


def _write_knowledge_items(items: list[dict[str, str]], *, source: str) -> int:
    if not items:
        return 0
    from tempa.rag.procedural import add_durable

    written = 0
    for item in items:
        tags = ["knowledge", "consolidation"]
        kind = item["kind"]
        text = item["text"]
        if kind == "person":
            email = _EMAIL_RE.search(text)
            if email:
                tags.append("email")
                try:
                    from tempa.channels.contacts.linker import lookup_identity

                    ident = lookup_identity(email.group(0))
                    if ident and ident.get("id"):
                        tags.append(f"identity:{ident['id']}")
                except Exception:
                    pass
        try:
            add_durable(text, kind=kind, source=source, tags=tags)
            written += 1
        except Exception:
            logger.debug("Knowledge durable write skipped", exc_info=True)
    return written


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
    """Consolidate recent episodic chunks into semantic summaries + durable knowledge."""
    chunks = _recent_chunks(hours=hours)
    if not chunks:
        return {"groups": 0, "summaries_written": 0, "knowledge_written": 0}

    groups: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        meta = chunk["metadata"]
        key = f"{meta.get('tool', 'unknown')}:{meta.get('source', 'unknown')}"
        groups[key].append(chunk["content"])

    written = 0
    knowledge_written = 0
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
        try:
            knowledge_written += _write_knowledge_items(
                _extract_knowledge_items(summary),
                source=f"{source}:consolidation",
            )
        except Exception:
            logger.debug("Knowledge extract failed for %s", key, exc_info=True)

    logger.info(
        "Memory consolidation: %s groups, %s summaries, %s knowledge",
        len(groups),
        written,
        knowledge_written,
    )
    return {
        "groups": len(groups),
        "summaries_written": written,
        "knowledge_written": knowledge_written,
    }
