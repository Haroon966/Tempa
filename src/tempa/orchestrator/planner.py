from __future__ import annotations

from typing import Any

from tempa.agents.tool_policy import filter_subtasks
from tempa.orchestrator.registry import filter_workers_for_context
from tempa.skills.matcher import match_skills
from tempa.skills.routing import skill_routing_hints, workers_from_skills


def _skill_biased_subtasks(user_message: str, context: dict[str, Any], skills) -> list[dict[str, Any]]:
    hints = skill_routing_hints(skills)
    tasks: list[dict[str, Any]] = [{"agent": "rag", "task": user_message}]
    for worker_id in workers_from_skills(skills):
        if worker_id == "rag":
            continue
        allowed = filter_workers_for_context({worker_id}, context)
        if worker_id in allowed:
            tasks.append({"agent": worker_id, "task": user_message})
    if len(tasks) > 1:
        return tasks
    return []


def plan_orchestrator_tasks(user_message: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ctx = dict(context or {})
    skills = match_skills(user_message, ctx)
    ctx["matched_skills"] = [s.name for s in skills]
    ctx["skill_routing"] = skill_routing_hints(skills)

    biased = _skill_biased_subtasks(user_message, ctx, skills)
    from tempa.agents.specialists import plan_subtasks

    if biased:
        subtasks = biased
    else:
        subtasks = plan_subtasks(user_message, ctx)

    subtasks = filter_subtasks(subtasks, ctx)

    has_rag = any(t.get("agent") == "rag" for t in subtasks)
    if not has_rag:
        subtasks.insert(0, {"agent": "rag", "task": f"Retrieve context for: {user_message}"})

    return subtasks
