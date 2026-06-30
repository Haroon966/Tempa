from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from tempa.agents.config import load_agents_config
from tempa.orchestrator.config import allowed_workers_for_context


@dataclass
class WorkerSpec:
    id: str
    name: str
    role: str
    runner: str
    model_category: str = "text"
    tools: list[str] = field(default_factory=list)
    skill: str = ""
    always_run: bool = False


def _workers_from_config() -> dict[str, WorkerSpec]:
    cfg = load_agents_config()
    block = cfg.get("workers") or cfg.get("specialists") or {}
    workers: dict[str, WorkerSpec] = {}
    for wid, meta in block.items():
        if not isinstance(meta, dict):
            continue
        runner = str(meta.get("worker") or meta.get("runner") or wid)
        workers[wid] = WorkerSpec(
            id=wid,
            name=str(meta.get("name") or wid),
            role=str(meta.get("role") or ""),
            runner=runner,
            model_category=str(meta.get("model_category") or "text"),
            tools=[str(t) for t in (meta.get("tools") or [])],
            skill=str(meta.get("skill") or ""),
            always_run=bool(meta.get("always_run", wid == "rag")),
        )
    return workers


@lru_cache
def list_workers() -> list[WorkerSpec]:
    return list(_workers_from_config().values())


def get_worker(worker_id: str) -> WorkerSpec | None:
    return _workers_from_config().get(worker_id)


def filter_workers_for_context(worker_ids: set[str], context: dict[str, Any] | None) -> set[str]:
    allowed = allowed_workers_for_context(context)
    return {w for w in worker_ids if w in allowed}


def workers_for_skills(skill_names: list[str], context: dict[str, Any] | None = None) -> list[WorkerSpec]:
    from tempa.skills.loader import load_all_skills

    by_name = {s.name: s for s in load_all_skills()}
    ids: list[str] = []
    seen: set[str] = set()
    for name in skill_names:
        skill = by_name.get(name)
        if not skill:
            continue
        for wid in skill.workers:
            if wid not in seen:
                seen.add(wid)
                ids.append(wid)
    filtered = filter_workers_for_context(set(ids), context)
    return [w for w in (_workers_from_config().get(i) for i in ids) if w and w.id in filtered]


def orchestrator_manifest() -> dict[str, Any]:
    from tempa.plugins.registry import list_tools
    from tempa.skills.loader import load_all_skills

    cfg = load_agents_config()
    coord = cfg.get("coordinator") or {}
    workers = _workers_from_config()
    tool_list = list_tools()
    tool_by_worker: dict[str, list[str]] = {}
    for w in workers.values():
        tool_by_worker[w.id] = list(w.tools)
    return {
        "orchestrator": {
            "name": coord.get("name", "Tempa Orchestrator"),
            "role": coord.get("role", ""),
            "model_category": coord.get("model_category", "reasoning"),
        },
        "workers": [
            {
                "id": w.id,
                "name": w.name,
                "role": w.role,
                "runner": w.runner,
                "tools": w.tools,
                "skill": w.skill,
                "always_run": w.always_run,
            }
            for w in workers.values()
        ],
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "triggers": s.triggers,
                "workers": s.workers,
                "tools": s.tools,
                "channels": s.channels,
                "enabled": True,
            }
            for s in load_all_skills()
        ],
        "tools": tool_list,
    }
