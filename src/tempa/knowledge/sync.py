"""Knowledge directory refresh + vault ingest."""

from __future__ import annotations

from tempa.knowledge.directory import refresh_knowledge_directory


def refresh_and_sync_knowledge() -> dict:
    """Refresh knowledge/*.md and ingest into RAG."""
    from tempa.varys.vault_sync import ensure_vault_initialized, sync_vault_file

    ensure_vault_initialized()
    result = refresh_knowledge_directory()
    from pathlib import Path

    root = Path(result["path"])
    chunks = 0
    for path in sorted(root.glob("*.md")):
        chunks += int(sync_vault_file(path).get("chunks_created") or 0)
    result["rag_chunks"] = chunks
    return result
