from __future__ import annotations

from typing import Any

from tempa.orchestrator.config import load_orchestrator_config
from tempa.skills.loader import load_all_skills, load_skills_config
from tempa.skills.types import Skill


def _channel_name(context: dict[str, Any] | None) -> str:
    ctx = context or {}
    ch = str(ctx.get("channel") or "dashboard")
    if ch == "slack" or ctx.get("inbound_slack"):
        return "slack"
    if ch == "whatsapp":
        return "whatsapp"
    return "dashboard"


def _skill_allowed_for_context(skill: Skill, context: dict[str, Any] | None) -> bool:
    if not skill.channels:
        return True
    channel = _channel_name(context)
    return channel in skill.channels


def _worker_allowed(skill: Skill, context: dict[str, Any] | None) -> bool:
    from tempa.orchestrator.registry import filter_workers_for_context

    if not skill.workers:
        return True
    allowed = filter_workers_for_context(set(skill.workers), context)
    return bool(allowed)


def match_skills(user_message: str, context: dict[str, Any] | None = None) -> list[Skill]:
    cfg = load_skills_config()
    orch = load_orchestrator_config()
    max_active = int(cfg.get("max_active") or orch.max_active_skills)
    text = (user_message or "").strip().lower()
    matched: list[Skill] = []
    for skill in load_all_skills():
        if not _skill_allowed_for_context(skill, context):
            continue
        if not _worker_allowed(skill, context):
            continue
        if not skill.triggers:
            continue
        if any(trigger in text for trigger in skill.triggers):
            matched.append(skill)
    matched.sort(key=lambda s: (-s.priority, s.name))
    return matched[:max_active]
