"""Curator — archive stale auto-skills, keep high-value ones (Hermes-style)."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.learning.store import auto_skills_dir, is_immutable, load_usage

logger = logging.getLogger(__name__)


def archive_dir() -> Path:
    path = auto_skills_dir().parent / "archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_curator(*, min_uses_to_keep: int = 0, max_fail_ratio: float = 0.7) -> dict[str, Any]:
    """Archive auto-learned skills that fail often or are unused after many days."""
    usage = load_usage().get("skills") or {}
    archived: list[str] = []
    kept: list[str] = []
    now = datetime.now(timezone.utc)

    for skill_dir in sorted(auto_skills_dir().iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        name = skill_dir.name
        if is_immutable(name, str(skill_md)):
            kept.append(name)
            continue
        stats = usage.get(name) or {}
        uses = int(stats.get("uses") or 0)
        fails = int(stats.get("fail") or 0)
        age_days = 0.0
        try:
            mtime = datetime.fromtimestamp(skill_md.stat().st_mtime, tz=timezone.utc)
            age_days = (now - mtime).total_seconds() / 86400.0
        except OSError:
            pass

        fail_ratio = (fails / uses) if uses else 0.0
        # Archive if: old + never used, or used but mostly failing
        should_archive = (age_days >= 14 and uses == 0) or (
            uses >= 5 and fail_ratio >= max_fail_ratio
        )
        if should_archive and uses >= min_uses_to_keep:
            dest = archive_dir() / name
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.move(str(skill_dir), str(dest))
            archived.append(name)
            logger.info("Curator archived skill %s", name)
        else:
            kept.append(name)

    try:
        from tempa.skills.loader import reload_skills

        reload_skills()
    except Exception:
        pass

    return {"archived": archived, "kept": kept, "usage_skills": len(usage)}
