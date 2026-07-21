from __future__ import annotations

import json
import logging
from typing import Any

from tempa.agents.config import actor_loop_enabled, actor_max_steps, actor_replan_on_error
from tempa.agents.graph import _run_specialist_with_retry, collect_pending_from_results, compute_execution_waves
from tempa.core.cross_channel_conversation import format_conversation_lines
from tempa.core.events import event_bus
from tempa.orchestrator.step_verify import observe_step, verify_step

logger = logging.getLogger(__name__)

PAUSE_ACTION_TYPES = frozenset(
    {"email_send", "pc_write", "pc_delete", "pc_mkdir", "file_transfer"}
)

_STEP_LABELS = {
    "gmail": "Searching Gmail",
    "calendar": "Checking calendar",
    "meet": "Joining meeting",
    "channel": "Messaging",
    "plugin": "Running integrations",
    "qa": "Checking repos",
    "pc": "Running on PC",
    "rag": "Searching memory",
}


def should_use_actor_loop(subtasks: list[dict[str, Any]], context: dict[str, Any]) -> bool:
    if not actor_loop_enabled():
        return False
    others = [t for t in subtasks if t.get("agent") != "rag"]
    if len(others) > 1:
        return True
    if any(t.get("depends_on") for t in others):
        return True
    agents = {t.get("agent") for t in others}
    if "meet" in agents and "channel" in agents:
        return True
    from tempa.agents.intent import is_casual_greeting

    msg = str(context.get("user_message") or "")
    if is_casual_greeting(msg) and len(others) <= 1:
        return False
    return False


def needs_pause(pending_actions: list[dict[str, Any]]) -> bool:
    return any(p.get("type") in PAUSE_ACTION_TYPES for p in pending_actions)


def _check_cancelled(context: dict[str, Any]) -> None:
    from tempa.agents.graph import _check_cancelled

    _check_cancelled(context)


def _flatten_queue(subtasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    waves = compute_execution_waves(subtasks)
    return [task for wave in waves for task in wave]


async def _emit_step_status(context: dict[str, Any], agent: str) -> None:
    sink = context.get("stream_sink")
    if not sink:
        return
    label = _STEP_LABELS.get(agent, f"Running {agent}")
    try:
        await sink(f"_{label}…_\n\n")
    except TypeError:
        result = sink(f"_{label}…_\n\n")
        if hasattr(result, "__await__"):
            await result


async def _replan_or_clarify(
    user_message: str,
    failed_agent: str,
    failed_reason: str,
    context: dict[str, Any],
    remaining: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]] | None, str | None]:
    if not actor_replan_on_error():
        return (
            "clarify",
            None,
            f"I couldn't complete the {failed_agent} step: {failed_reason}. What should I do?",
        )

    from tempa.agents.config import model_category_for_agent
    from tempa.router.groq_router import get_router

    conv = format_conversation_lines(context.get("conversation_messages") or [], limit=8)
    router = get_router()
    prompt = (
        "A coordinator step failed. Choose next action.\n"
        'Return JSON only: {"action": "replan"|"clarify", "question": "...", '
        '"subtasks": [{"agent": "...", "task": "...", "depends_on": []}]}\n'
        f"Failed agent: {failed_agent}\nReason: {failed_reason}\n"
        f"Remaining steps: {json.dumps(remaining, ensure_ascii=False)}\n"
        f"Conversation:\n" + "\n".join(conv) + "\n"
        f"User message: {user_message}"
    )
    try:
        response = router.chat_completion(
            category=model_category_for_agent("coordinator", "reasoning"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        action = str(data.get("action") or "clarify")
        if action == "replan" and isinstance(data.get("subtasks"), list):
            return "replan", data["subtasks"], None
        question = str(
            data.get("question")
            or f"Step {failed_agent} failed ({failed_reason}). How should I proceed?"
        )
        return "clarify", None, question
    except Exception as exc:
        logger.warning("Replan failed: %s", exc)
        return (
            "clarify",
            None,
            f"I couldn't complete the {failed_agent} step: {failed_reason}. What should I do?",
        )


async def run_actor_loop(
    user_message: str,
    subtasks: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    task_id: str = "",
    existing_results: dict[str, str] | None = None,
    queue_override: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, Any], bool, list[dict[str, Any]], str | None]:
    """Run non-rag subtasks sequentially. RAG should already be in existing_results."""
    results = dict(existing_results or {})
    ctx = dict(context)
    ctx.setdefault("action_facts", [])
    ctx.setdefault("step_results", [])

    others = queue_override if queue_override is not None else [t for t in subtasks if t.get("agent") != "rag"]
    queue = _flatten_queue(others)
    ctx["planned_steps"] = [
        {"agent": t.get("agent"), "task": str(t.get("task", ""))[:120]} for t in queue
    ]

    plan_summary = json.dumps(ctx["planned_steps"], ensure_ascii=False)
    await event_bus.publish_json("orchestrator", "activity", f"plan:{plan_summary[:400]}")

    pending_actions: list[dict[str, Any]] = []
    paused = False
    clarification: str | None = None
    step_count = 0
    idx = 0

    while idx < len(queue) and step_count < actor_max_steps():
        _check_cancelled(ctx)
        task = queue[idx]
        agent = str(task.get("agent") or "")
        task_text = str(task.get("task") or user_message)
        step_id = str(task.get("_id") or f"{agent}-{idx}")

        await event_bus.publish_json("orchestrator", "activity", f"step_start:{agent}")
        await _emit_step_status(ctx, agent)

        raw = await _run_specialist_with_retry(agent, task_text, ctx, user_message, task_id, step_id)
        results[agent] = raw
        ctx[f"{agent}_result"] = raw

        payload = observe_step(ctx, agent, raw, subtask_id=step_id, task=task_text)
        ok, reason = verify_step(agent, raw, payload)
        await event_bus.publish_json(
            "orchestrator", "activity", f"step_done:{agent}:{reason or 'ok'}"
        )

        step_pending = collect_pending_from_results({agent: raw})
        if step_pending:
            seen = {p["id"] for p in pending_actions if p.get("id")}
            for item in step_pending:
                if item.get("id") not in seen:
                    pending_actions.append(item)
                    seen.add(item.get("id"))
            if needs_pause(step_pending):
                paused = True
                idx += 1
                break

        if not ok and reason != "pending":
            action, new_tasks, question = await _replan_or_clarify(
                user_message, agent, reason, ctx, queue[idx + 1 :]
            )
            if action == "replan" and new_tasks:
                await event_bus.publish_json("orchestrator", "activity", "replan")
                queue = queue[: idx + 1] + _flatten_queue(new_tasks)
            else:
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

        idx += 1
        step_count += 1

    all_pending = collect_pending_from_results(results)
    seen_ids = {p["id"] for p in pending_actions if p.get("id")}
    for item in all_pending:
        if item.get("id") not in seen_ids:
            pending_actions.append(item)
            seen_ids.add(item.get("id"))

    if not paused:
        paused = needs_pause(pending_actions)

    return results, ctx, paused, pending_actions, clarification
