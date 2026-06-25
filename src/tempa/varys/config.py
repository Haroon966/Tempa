from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tempa.settings import get_settings


@dataclass
class VarysConfig:
    agent_name: str = "Tempa"
    owner_name: str = ""
    owner_slack_user_id: str = ""
    orchestrator_tick_seconds: int = 270
    notion_enabled: bool = False
    repos: list[dict[str, Any]] = field(default_factory=list)


def load_varys_config() -> VarysConfig:
    settings = get_settings()
    path = settings.config_dir / "varys.yaml"
    if not path.exists():
        return VarysConfig(
            agent_name=settings.varys_agent_name or "Tempa",
            owner_name=settings.varys_owner_name,
            owner_slack_user_id=settings.slack_owner_user_id,
            orchestrator_tick_seconds=settings.varys_tick_seconds,
            notion_enabled=settings.notion_enabled,
            repos=[],
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return VarysConfig(
        agent_name=str(raw.get("agent_name") or settings.varys_agent_name or "Tempa"),
        owner_name=str(raw.get("owner_name") or settings.varys_owner_name or ""),
        owner_slack_user_id=str(
            raw.get("owner_slack_user_id") or settings.slack_owner_user_id or ""
        ),
        orchestrator_tick_seconds=int(
            raw.get("orchestrator_tick_seconds") or settings.varys_tick_seconds
        ),
        notion_enabled=bool(raw.get("notion_enabled", settings.notion_enabled)),
        repos=list(raw.get("repos") or []),
    )


def rules_dir() -> Path:
    return get_settings().config_dir / "varys" / "rules"


def vault_templates_dir() -> Path:
    return get_settings().config_dir / "varys" / "vault-templates"


def load_rules_text() -> str:
    parts: list[str] = []
    base = rules_dir()
    if not base.is_dir():
        return ""
    for path in sorted(base.glob("*.md")):
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts)
