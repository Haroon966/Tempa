from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from tempa.settings import get_settings


@lru_cache
def load_agents_config() -> dict[str, Any]:
    path = get_settings().config_dir / "agents.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def model_category_for_agent(agent: str, default: str = "text") -> str:
    cfg = load_agents_config()
    specialists = cfg.get("specialists") or {}
    entry = specialists.get(agent) or {}
    return str(entry.get("model_category") or default)


def plan_preview_enabled() -> bool:
    cfg = load_agents_config()
    coordinator = cfg.get("coordinator") or {}
    return bool(coordinator.get("plan_preview", False))
