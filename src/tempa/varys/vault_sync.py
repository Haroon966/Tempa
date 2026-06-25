from __future__ import annotations

import logging
import shutil
from pathlib import Path

from tempa.rag.ingest import ingest_text
from tempa.settings import get_settings
from tempa.varys.config import vault_templates_dir

logger = logging.getLogger(__name__)


def _vault_path_to_wing_room(path: Path, vault_root: Path) -> tuple[str, str, str]:
    rel = path.relative_to(vault_root)
    parts = rel.parts
    wing = "workspace"
    room = "memory"
    if len(parts) >= 2 and parts[0] == "projects":
        wing = parts[1]
        room = parts[2] if len(parts) > 2 else "project"
    elif len(parts) >= 1:
        room = parts[0]
    drawer = path.stem
    return wing, room, drawer


def ensure_vault_initialized() -> Path:
    settings = get_settings()
    vault = settings.varys_vault_dir
    vault.mkdir(parents=True, exist_ok=True)
    templates = vault_templates_dir()
    if templates.is_dir():
        for src in templates.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(templates)
            dest = vault / rel
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    return vault


def sync_vault_file(path: Path) -> dict[str, int]:
    settings = get_settings()
    vault = settings.varys_vault_dir.resolve()
    path = path.resolve()
    if not str(path).startswith(str(vault)):
        return {"chunks_created": 0}
    if path.suffix.lower() not in {".md", ".txt"}:
        return {"chunks_created": 0}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"chunks_created": 0}
    wing, room, drawer = _vault_path_to_wing_room(path, vault)
    rel_source = str(path.relative_to(vault))
    return ingest_text(
        text,
        tool="vault",
        source=rel_source,
        tags=["vault", wing, room],
        wing=wing,
        room=room,
        drawer=drawer,
        memory_class="project" if wing != "workspace" else "episodic",
    )


def mine_vault() -> dict[str, int]:
    vault = ensure_vault_initialized()
    total_chunks = 0
    files = 0
    for path in vault.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            result = sync_vault_file(path)
            total_chunks += int(result.get("chunks_created") or 0)
            files += 1
    return {"files": files, "chunks_created": total_chunks}


def detect_wing_from_cwd(cwd: Path | None = None) -> str:
    settings = get_settings()
    root = (cwd or Path.cwd()).resolve()
    vault = settings.varys_vault_dir
    projects = vault / "projects"
    if projects.is_dir():
        for child in projects.iterdir():
            try:
                root.relative_to(child.resolve())
                return child.name
            except ValueError:
                continue
    if root == settings.project_root.resolve():
        return "tempa"
    return "workspace"


def append_session_log(summary: str) -> None:
    from datetime import datetime, timezone

    vault = ensure_vault_initialized()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = vault / "logs" / f"{day}.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H:%M")
    line = f"- {stamp} — {summary.strip()}\n"
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            line = "\n" + line
        log_path.write_text(existing + line, encoding="utf-8")
    else:
        log_path.write_text(f"# Session log {day}\n\n{line}", encoding="utf-8")
    sync_vault_file(log_path)
