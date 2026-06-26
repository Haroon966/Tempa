from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tempa.rag.ingest import search_memory
from tempa.settings import get_settings
from tempa.plugins.registry import list_tools
from tempa.varys.config import load_rules_text, load_varys_config

logger = logging.getLogger(__name__)


def _tool_manifest() -> str:
    from tempa.plugins.registry import load_builtin_plugins

    load_builtin_plugins()
    lines = ["Available Tempa tools (invoke via coordinator specialists when needed):"]
    for tool in list_tools():
        lines.append(f"- {tool['name']}: {tool['description']}")
    return "\n".join(lines)


def detect_project_wing(cwd: Path | None = None) -> str:
    settings = get_settings()
    root = (cwd or settings.project_root).resolve()
    vault = settings.varys_vault_dir
    projects = vault / "projects"
    if projects.is_dir():
        for child in projects.iterdir():
            if child.is_dir() and root == child.resolve():
                return child.name
    if root == settings.project_root.resolve():
        return "tempa"
    return "workspace"


def _read_vault_snippets(wing: str, *, max_chars: int = 6000) -> str:
    settings = get_settings()
    vault = settings.varys_vault_dir
    parts: list[str] = []
    total = 0
    candidates: list[Path] = []
    for sub in ("memory", f"projects/{wing}", "logs"):
        base = vault / sub
        if base.is_dir():
            candidates.extend(sorted(base.rglob("*.md")))
    for path in candidates[:20]:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue
        rel = path.relative_to(vault)
        chunk = f"### {rel}\n{text}\n"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts)


def build_context(
    user_message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from tempa.core.cross_channel_conversation import enrich_conversation_context

    ctx = enrich_conversation_context(dict(context or {}))
    cfg = load_varys_config()
    wing = str(ctx.get("varys_wing") or detect_project_wing())
    rules = load_rules_text()
    vault_text = _read_vault_snippets(wing)
    rag_hits: list[dict[str, Any]] = []
    try:
        rag_hits = search_memory(user_message, top_k=5, wing=wing)
    except Exception as exc:
        logger.warning("RAG search failed in varys context: %s", exc)

    memory_lines = []
    for hit in rag_hits[:5]:
        meta = hit.get("metadata") or {}
        memory_lines.append(
            f"- [{meta.get('wing', '')}/{meta.get('room', '')}] {hit.get('content', '')[:400]}"
        )

    recent = ctx.get("recent_conversation") or []
    convo_lines = []
    if isinstance(recent, list):
        from tempa.core.cross_channel_conversation import format_conversation_lines

        convo_lines = format_conversation_lines(recent, limit=16)

    system_parts = [
        f"You are {cfg.agent_name}, a personal AI assistant integrated with Tempa.",
        f"Active memory wing: {wing}.",
    ]
    if rules:
        system_parts.append("## Rules\n" + rules)
    if vault_text:
        system_parts.append("## Vault context\n" + vault_text)
    if memory_lines:
        system_parts.append("## Retrieved memory\n" + "\n".join(memory_lines))
    try:
        system_parts.append("## Tools\n" + _tool_manifest())
    except Exception:
        pass

    user_parts = []
    if convo_lines:
        user_parts.append("## Recent conversation (all channels)\n" + "\n".join(convo_lines))
    user_parts.append("## Current message\n" + user_message)

    return {
        "wing": wing,
        "system": "\n\n".join(system_parts),
        "user": "\n\n".join(user_parts),
        "rag_hits": rag_hits,
        "sources": [
            {
                "tool": (h.get("metadata") or {}).get("tool", ""),
                "source": (h.get("metadata") or {}).get("source", ""),
                "wing": (h.get("metadata") or {}).get("wing", ""),
            }
            for h in rag_hits
        ],
    }
