from __future__ import annotations

import asyncio
from typing import Any

from tempa.agents.graph import compute_execution_waves
from tempa.core.events import event_bus


async def delegate_tasks(
    user_message: str,
    subtasks: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    task_id: str = "",
    existing_results: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    from tempa.agents.graph import _run_specialist_with_retry
    from tempa.agents.tool_policy import filter_subtasks

    if not subtasks:
        return dict(existing_results or {}), context

    subtasks = filter_subtasks(subtasks, context)
    if not subtasks:
        return dict(existing_results or {}), context

    waves = compute_execution_waves(subtasks)
    results = dict(existing_results or {})
    ctx = dict(context)

    await event_bus.publish_json("orchestrator", "delegate", f"{len(subtasks)} subtasks, {len(waves)} waves")

    for wave_index, wave in enumerate(waves):
        await event_bus.publish_json(
            "orchestrator",
            "wave",
            f"wave {wave_index + 1}/{len(waves)}",
        )
        ctx["specialist_results"] = results
        ctx["matched_skills"] = context.get("matched_skills") or []
        coros = [
            _run_specialist_with_retry(
                str(task.get("agent")),
                str(task.get("task", "")),
                ctx,
                user_message,
                task_id,
                str(task.get("_id") or task.get("agent")),
            )
            for task in wave
        ]
        wave_results = await asyncio.gather(*coros)
        for task, result in zip(wave, wave_results):
            agent = str(task.get("agent"))
            results[agent] = result
            ctx[f"{agent}_result"] = result

    return results, ctx
