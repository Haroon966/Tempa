from __future__ import annotations

from typing import Any

from tempa.rag.ingest import search_memory
from tempa.rag.filters import extract_filters_from_query


def retrieve(
    query: str,
    *,
    top_k: int = 5,
    tool: str | None = None,
    filters: dict[str, Any] | None = None,
) -> str:
    merged = dict(filters or {})
    if tool and "tool" not in merged:
        merged["tool"] = tool
    if not merged:
        merged = extract_filters_from_query(query)
    results = search_memory(
        query,
        top_k=top_k,
        tool=merged.get("tool"),
        meet_link=merged.get("meet_link"),
        date_from=merged.get("date_from"),
        date_to=merged.get("date_to"),
        participant=merged.get("participant"),
        tags=merged.get("tags"),
    )
    if not results:
        return ""
    parts = []
    for item in results:
        meta = item["metadata"]
        header = f"[{meta.get('tool', '?')}/{meta.get('source', '?')}]"
        parts.append(f"{header}\n{item['content']}")
    return "\n\n---\n\n".join(parts)


def retrieve_with_sources(
    query: str,
    *,
    top_k: int = 5,
    tool: str | None = None,
    filters: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    merged = dict(filters or {})
    if tool and "tool" not in merged:
        merged["tool"] = tool
    if not merged:
        merged = extract_filters_from_query(query)
    results = search_memory(
        query,
        top_k=top_k,
        tool=merged.get("tool"),
        meet_link=merged.get("meet_link"),
        date_from=merged.get("date_from"),
        date_to=merged.get("date_to"),
        participant=merged.get("participant"),
        tags=merged.get("tags"),
    )
    if not results:
        return "", []
    parts = []
    sources: list[dict[str, Any]] = []
    for item in results:
        meta = item["metadata"]
        label = f"{meta.get('tool', '?')}/{meta.get('source', '?')}"
        if meta.get("title"):
            label = f"{meta.get('tool')}/{meta.get('title')}"
        header = f"[{label}]"
        parts.append(f"{header}\n{item['content']}")
        sources.append(
            {
                "label": label,
                "tool": meta.get("tool"),
                "source": meta.get("source"),
                "title": meta.get("title") or "",
                "timestamp": meta.get("timestamp") or "",
                "score": item.get("score"),
            }
        )
    return "\n\n---\n\n".join(parts), sources
