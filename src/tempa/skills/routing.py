from __future__ import annotations

from typing import Any

from tempa.skills.types import Skill


def skill_routing_hints(skills: list[Skill]) -> dict[str, Any]:
    workers: set[str] = set()
    tools: set[str] = set()
    for skill in skills:
        workers.update(skill.workers)
        tools.update(skill.tools)
    return {"workers": sorted(workers), "tools": sorted(tools)}


def workers_from_skills(skills: list[Skill]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for skill in sorted(skills, key=lambda s: -s.priority):
        for worker in skill.workers:
            if worker not in seen:
                seen.add(worker)
                ordered.append(worker)
    return ordered
