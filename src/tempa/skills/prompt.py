from __future__ import annotations

from tempa.orchestrator.config import load_orchestrator_config
from tempa.skills.types import Skill


def format_skills_for_prompt(skills: list[Skill]) -> str:
    if not skills:
        return ""
    max_chars = load_orchestrator_config().skill_body_max_chars
    parts: list[str] = []
    for skill in skills:
        body = skill.body.strip()
        if len(body) > max_chars:
            body = body[: max_chars - 3] + "..."
        parts.append(f"### Skill: {skill.name}\n{skill.description}\n\n{body}")
    return "\n\n".join(parts)
