from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from tempa.settings import get_settings


@lru_cache
def load_qa_config() -> dict[str, Any]:
    path = get_settings().config_dir / "qa.yaml"
    if not path.exists():
        return {"enabled": True}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def qa_enabled() -> bool:
    settings = get_settings()
    if not settings.tempa_qa_enabled:
        return False
    return bool(load_qa_config().get("enabled", True))


def qa_data_dir() -> Path:
    return get_settings().sessions_dir / "qa"


def qa_worktrees_dir() -> Path:
    return get_settings().tempa_data_dir / "qa" / "worktrees"
