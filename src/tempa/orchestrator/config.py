from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from tempa.settings import get_settings

ALL_WORKERS = frozenset({"rag", "channel", "plugin", "gmail", "calendar", "meet", "qa", "pc"})


@dataclass
class OrchestratorConfig:
    merge_backend: str = "groq"
    max_parallel_workers: int = 4
    max_active_skills: int = 3
    pre_hooks_enabled: bool = True
    skill_body_max_chars: int = 1500
    guest_slack_workers: frozenset[str] = field(
        default_factory=lambda: frozenset({"rag", "channel", "plugin"})
    )
    owner_workers: frozenset[str] = field(default_factory=lambda: ALL_WORKERS)


@lru_cache
def load_orchestrator_config() -> OrchestratorConfig:
    path = get_settings().config_dir / "orchestrator.yaml"
    if not path.exists():
        return OrchestratorConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    matrix = raw.get("channel_matrix") or {}
    guest = matrix.get("guest_slack") or {}
    guest_workers = guest.get("allowed_workers") or ["rag", "channel", "plugin"]
    guest_set = ALL_WORKERS if guest_workers == "all" else frozenset(str(w) for w in guest_workers)
    owner_block = matrix.get("owner") or {}
    owner_list = owner_block.get("allowed_workers") or "all"
    owner_set = ALL_WORKERS if owner_list == "all" else frozenset(str(w) for w in owner_list)
    return OrchestratorConfig(
        merge_backend=str(raw.get("merge_backend") or "groq"),
        max_parallel_workers=int(raw.get("max_parallel_workers") or 4),
        max_active_skills=int(raw.get("max_active_skills") or 3),
        pre_hooks_enabled=bool(raw.get("pre_hooks_enabled", True)),
        skill_body_max_chars=int(raw.get("skill_body_max_chars") or 1500),
        guest_slack_workers=guest_set,
        owner_workers=owner_set,
    )


def allowed_workers_for_context(context: dict[str, Any] | None) -> frozenset[str]:
    from tempa.agents.tool_policy import is_slack_guest

    cfg = load_orchestrator_config()
    if is_slack_guest(context):
        return cfg.guest_slack_workers
    return cfg.owner_workers
