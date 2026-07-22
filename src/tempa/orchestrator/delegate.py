from __future__ import annotations

from typing import Any

from tempa.agents.graph import compute_execution_waves
from tempa.core.events import event_bus
from tempa.orchestrator.parallel import gather_limited
from tempa.orchestrator.step_verify import observe_step, verify_step


async def delegate_tasks(
    user_message: str,
    subtasks: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    task_id: str = "",
    existing_results: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any], str | None]:
    """Run specialist waves. Returns (results, context, clarification_or_none)."""
    from tempa.agents.graph import _run_specialist_with_retry
    from tempa.agents.tool_policy import filter_subtasks
    from tempa.orchestrator.actor_loop import _replan_or_clarify

    if not subtasks:
        return dict(existing_results or {}), context, None

    subtasks = filter_subtasks(subtasks, context)
    if not subtasks:
        return dict(existing_results or {}), context, None

    waves = compute_execution_waves(subtasks)
    results = dict(existing_results or {})
    ctx = dict(context)
    ctx.setdefault("action_facts", [])
    ctx.setdefault("step_results", [])
    ctx["planned_steps"] = [
        {"agent": t.get("agent"), "task": str(t.get("task", ""))[:120]}
        for wave in waves
        for t in wave
    ]

    await event_bus.publish_json("orchestrator", "delegate", f"{len(subtasks)} subtasks, {len(waves)} waves")

    clarification: str | None = None

    for wave_index, wave in enumerate(waves):
        if clarification:
            break
        await event_bus.publish_json(
            "orchestrator",
            "wave",
            f"wave {wave_index + 1}/{len(waves)}",
        )
        ctx["specialist_results"] = results
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
        wave_results = await gather_limited(coros)
        remaining_after_wave = [
            t for later in waves[wave_index + 1 :] for t in later
        ]
        for task, result in zip(wave, wave_results):
            agent = str(task.get("agent"))
            step_id = str(task.get("_id") or agent)
            results[agent] = result
            ctx[f"{agent}_result"] = result
            payload = observe_step(
                ctx,
                agent,
                result,
                subtask_id=step_id,
                task=str(task.get("task", "")),
            )
            ok, reason = verify_step(agent, result, payload)
            if ok or reason == "pending":
                continue
            action, new_tasks, question = await _replan_or_clarify(
                user_message,
                agent,
                reason,
                ctx,
                remaining_after_wave,
            )
            if action == "replan" and new_tasks:
                await event_bus.publish_json("orchestrator", "activity", "replan")
                extra_results, ctx, extra_clarify = await delegate_tasks(
                    user_message,
                    list(new_tasks),
                    ctx,
                    task_id=task_id,
                    existing_results=results,
                )
                results.update(extra_results)
                if extra_clarify:
                    clarification = extra_clarify
                break
            clarification = question
            if question:
                try:
                    from tempa.rag.procedural import (
                        _infer_slot_from_question,
                        register_open_clarification,
                    )

                    register_open_clarification(
                        question,
                        slot=_infer_slot_from_question(question),
                        context=ctx,
                    )
                except Exception:
                    pass
            await event_bus.publish_json(
                "orchestrator",
                "activity",
                f"clarify:{(question or '')[:80]}",
            )
            break

    return results, ctx, clarification
