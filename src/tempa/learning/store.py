from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()

_IMMUTABLE = frozenset({"slack-routing-policy"})


def auto_skills_dir() -> Path:
    from tempa.settings import get_settings

    path = get_settings().tempa_data_dir / "skills" / "auto"
    path.mkdir(parents=True, exist_ok=True)
    return path


def usage_path() -> Path:
    from tempa.settings import get_settings

    path = get_settings().tempa_data_dir / "skills" / "usage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str, *, max_len: int = 40) -> str:
    s = "".join(c if c.isalnum() else "-" for c in (text or "").lower()).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return (s or "skill")[:max_len]


def is_immutable(name: str, path: str = "") -> bool:
    if name in _IMMUTABLE:
        return True
    if "/slack-routing-policy/" in path.replace("\\", "/"):
        return True
    try:
        p = Path(path) if path else None
        if p and p.is_file():
            text = p.read_text(encoding="utf-8")[:800]
            return "immutable: true" in text.lower() or "immutable:true" in text.lower()
    except OSError:
        pass
    return False


def record_skill_usage(skill_names: list[str], *, success: bool) -> None:
    if not skill_names:
        return
    with _lock:
        path = usage_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        skills = data.setdefault("skills", {})
        for name in skill_names:
            entry = skills.setdefault(name, {"uses": 0, "success": 0, "fail": 0, "updated_at": _now()})
            entry["uses"] = int(entry.get("uses") or 0) + 1
            if success:
                entry["success"] = int(entry.get("success") or 0) + 1
            else:
                entry["fail"] = int(entry.get("fail") or 0) + 1
            entry["updated_at"] = _now()
        data["updated_at"] = _now()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_usage() -> dict[str, Any]:
    path = usage_path()
    if not path.exists():
        return {"skills": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"skills": {}}
    except Exception:
        return {"skills": {}}


def write_skill_md(
    name: str,
    *,
    description: str,
    triggers: list[str],
    workers: list[str],
    body: str,
    priority: int = 20,
    channels: list[str] | None = None,
) -> Path:
    safe = _slug(name)
    dest = auto_skills_dir() / safe
    dest.mkdir(parents=True, exist_ok=True)
    triggers = [str(t).lower().strip() for t in triggers if str(t).strip()][:12]
    workers = [str(w).strip() for w in workers if str(w).strip()][:8]
    channels = channels or []
    meta = {
        "name": safe,
        "description": (description or safe)[:200],
        "triggers": triggers,
        "workers": workers,
        "channels": channels,
        "priority": priority,
        "auto_learned": True,
        "updated_at": _now(),
    }
    front = yaml_dump_frontmatter(meta)
    text = f"---\n{front}---\n\n{body.strip()}\n"
    path = dest / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    try:
        from tempa.skills.loader import reload_skills

        reload_skills()
    except Exception:
        pass
    return path


def yaml_dump_frontmatter(meta: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(meta, default_flow_style=False, sort_keys=False)


def read_skill_path(name: str) -> Path | None:
    from tempa.skills.loader import load_all_skills

    for skill in load_all_skills():
        if skill.name == name and skill.path:
            return Path(skill.path)
    auto = auto_skills_dir() / _slug(name) / "SKILL.md"
    return auto if auto.is_file() else None


def append_skill_section(path: Path, section: str) -> None:
    if is_immutable(path.parent.name, str(path)):
        return
    text = path.read_text(encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = f"\n\n## Learned refinement ({stamp})\n\n{section.strip()}\n"
    if section.strip() and section.strip() not in text:
        path.write_text(text.rstrip() + block, encoding="utf-8")
        try:
            from tempa.skills.loader import reload_skills

            reload_skills()
        except Exception:
            pass


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def llm_json(prompt: str, *, max_tokens: int = 700) -> dict[str, Any]:
    try:
        from tempa.agents.config import model_category_for_agent
        from tempa.router.groq_router import get_router

        router = get_router()
        response = router.chat_completion(
            category=model_category_for_agent("coordinator", "reasoning"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=0.2,
        )
        return _parse_json_object(response.choices[0].message.content or "")
    except Exception as exc:
        logger.debug("learning llm_json failed: %s", exc)
        return {}
