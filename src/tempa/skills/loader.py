from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from tempa.settings import get_settings
from tempa.skills.types import Skill

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_skill_file(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FRONTMATTER_RE.match(text.strip() + "\n" if not text.endswith("\n") else text)
    if not match:
        return None
    meta_raw, body = match.group(1), match.group(2).strip()
    try:
        meta = yaml.safe_load(meta_raw) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    name = str(meta.get("name") or path.parent.name)
    workers = meta.get("workers") or meta.get("specialists") or []
    return Skill(
        name=name,
        description=str(meta.get("description") or ""),
        body=body,
        triggers=[str(t).lower() for t in (meta.get("triggers") or [])],
        workers=[str(w) for w in workers],
        tools=[str(t) for t in (meta.get("tools") or [])],
        channels=[str(c) for c in (meta.get("channels") or [])],
        priority=int(meta.get("priority") or 0),
        path=str(path),
    )


@lru_cache
def load_skills_config() -> dict:
    path = get_settings().config_dir / "skills.yaml"
    if not path.exists():
        return {"enabled": True, "directories": ["config/skills"], "disabled": [], "max_active": 3}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _skill_directories() -> list[Path]:
    cfg = load_skills_config()
    root = get_settings().config_dir.parent
    dirs: list[Path] = []
    for entry in cfg.get("directories") or ["config/skills"]:
        p = Path(entry)
        if not p.is_absolute():
            p = root / entry
        if p.is_dir():
            dirs.append(p)
    default = get_settings().config_dir / "skills"
    if default.is_dir() and default not in dirs:
        dirs.append(default)
    return dirs


def load_all_skills() -> list[Skill]:
    cfg = load_skills_config()
    if not cfg.get("enabled", True):
        return []
    disabled = {str(d) for d in (cfg.get("disabled") or [])}
    skills: list[Skill] = []
    seen: set[str] = set()
    for base in _skill_directories():
        for path in sorted(base.glob("*/SKILL.md")):
            skill = _parse_skill_file(path)
            if skill is None or skill.name in disabled or skill.name in seen:
                continue
            seen.add(skill.name)
            skills.append(skill)
    return skills
