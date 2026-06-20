from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from tempa.agents.specialists import (
    merge_results,
    merge_results_stream,
    plan_subtasks,
    run_calendar_agent,
    run_channel_agent,
    run_gmail_agent,
    run_meet_agent,
    run_pc_agent,
    run_plugin_agent,
    run_rag_agent_task,
)
from tempa.core.events import event_bus

AGENT_RUNNERS = {
    "meet": run_meet_agent,
    "channel": run_channel_agent,
    "calendar": run_calendar_agent,
    "gmail": run_gmail_agent,
    "pc": run_pc_agent,
    "plugin": run_plugin_agent,
}

MAX_SPECIALIST_RETRIES = 2

DESTRUCTIVE_AGENTS = frozenset({"pc", "gmail", "channel"})


def merge_dicts(left: dict[str, str] | None, right: dict[str, str] | None) -> dict[str, str]:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class CoordinatorState(TypedDict, total=False):
    user_message: str
    context: dict[str, Any]
    rag_task: dict[str, Any]
    subtasks: list[dict[str, Any]]
    results: Annotated[dict[str, str], merge_dicts]
    response: str
    task_id: str
    sources: list[dict[str, Any]]
    paused: bool


def compute_execution_waves(subtasks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Topological sort into execution waves honoring depends_on."""
    if not subtasks:
        return []

    tasks = []
    for index, task in enumerate(subtasks):
        entry = dict(task)
        entry.setdefault("_id", f"task_{index}")
        tasks.append(entry)

    remaining = list(tasks)
    done_agents: set[str] = set()
    done_ids: set[str] = set()
    waves: list[list[dict[str, Any]]] = []

    while remaining:
        wave: list[dict[str, Any]] = []
        next_remaining: list[dict[str, Any]] = []
        for task in remaining:
            deps = task.get("depends_on") or []
            if all(dep in done_agents or dep in done_ids for dep in deps):
                wave.append(task)
            else:
                next_remaining.append(task)
        if not wave and next_remaining:
            wave = next_remaining
            next_remaining = []
        waves.append(wave)
        for task in wave:
            done_ids.add(str(task.get("_id")))
            done_agents.add(str(task.get("agent")))
        remaining = next_remaining
    return waves


def _task_needs_destructive_preview(subtasks: list[dict[str, Any]], user_message: str) -> bool:
    lower = user_message.lower()
    for task in subtasks:
        agent = task.get("agent", "")
        task_text = str(task.get("task", "")).lower()
        if agent == "pc":
            return True
        if agent == "channel" and any(k in task_text or k in lower for k in ("send", "message", "notify", "reply")):
            return True
        if agent == "gmail" and any(k in task_text or k in lower for k in ("send", "compose", "reply", "forward")):
            return True
    return False


async def plan_node(state: CoordinatorState) -> dict[str, Any]:
    await event_bus.publish_json("coordinator", "plan", state["user_message"][:120])
    from tempa.core.task_store import create_task, format_active_tasks_summary
    from tempa.rag.procedural import format_preferences_for_prompt, maybe_capture_from_message

    context = dict(state.get("context") or {})
    active = format_active_tasks_summary()
    if active:
        context["active_tasks"] = active

    prefs = format_preferences_for_prompt()
    if prefs:
        context["procedural_memory"] = prefs

    maybe_capture_from_message(state["user_message"])

    if context.get("channel") == "whatsapp" and "recent_user_messages" not in context:
        try:
            from tempa.channels.whatsapp.conversation import get_recent_messages

            context["recent_user_messages"] = [
                m.get("text", "") for m in get_recent_messages(8) if m.get("role") == "user"
            ]
        except Exception:
            pass

    subtasks = plan_subtasks(state["user_message"], context)
    others = [t for t in subtasks if t.get("agent") != "rag"]
    task_id = create_task(state["user_message"], others)
    rag_task = next((t for t in subtasks if t.get("agent") == "rag"), None)
    if not rag_task:
        rag_task = {"agent": "rag", "task": f"Retrieve context for: {state['user_message']}"}
    return {
        "rag_task": rag_task,
        "subtasks": others,
        "results": {},
        "context": context,
        "task_id": task_id,
        "sources": [],
    }


async def plan_preview_node(state: CoordinatorState) -> dict[str, Any]:
    from tempa.agents.config import plan_preview_enabled
    from tempa.core.pending_actions import create_pending_action

    context = state.get("context") or {}
    if context.get("plan_approved") or not plan_preview_enabled():
        return {}

    subtasks = state.get("subtasks") or []
    if not _task_needs_destructive_preview(subtasks, state.get("user_message", "")):
        return {}

    plan_summary = json.dumps(subtasks, ensure_ascii=False, indent=2)
    action = create_pending_action(
        "plan_preview",
        {
            "user_message": state["user_message"],
            "context": context,
            "subtasks": subtasks,
            "plan_summary": plan_summary,
        },
        source_channel=str(context.get("channel") or "coordinator"),
        risk_level="medium",
        title="Review coordinator plan",
    )
    response = (
        "I've prepared an execution plan that includes actions requiring your approval. "
        f"Open Tempa Approvals to review (id: {action['id'][:8]}…).\n\n"
        f"Plan:\n{plan_summary}"
    )
    return {"response": response, "paused": True}


def route_after_preview(state: CoordinatorState) -> str:
    if state.get("paused"):
        return "end"
    return "rag_gate"


async def rag_gate_node(state: CoordinatorState) -> dict[str, Any]:
    """FR-CORE-04: Agentic RAG runs before specialist actions."""
    await event_bus.publish_json("coordinator", "rag_gate", "retrieving context before specialists")
    rag_task = state.get("rag_task") or {"agent": "rag", "task": state["user_message"]}
    context = dict(state.get("context") or {})
    context["user_message"] = state["user_message"]

    result, sources = await run_rag_agent_task(rag_task["task"], context)
    context["rag_context"] = result
    if sources:
        context["rag_sources"] = sources
    return {"results": {"rag": result}, "context": context, "sources": sources}


async def _run_specialist_with_retry(
    agent: str,
    task: str,
    context: dict[str, Any],
    user_message: str,
    task_id: str,
) -> str:
    runner = AGENT_RUNNERS.get(agent)
    if not runner:
        return f"Unknown agent: {agent}"
    ctx = dict(context)
    ctx["user_message"] = user_message
    if task_id:
        from tempa.core.task_store import update_subtask

        update_subtask(task_id, agent, "in_progress")
    result = ""
    last_error = ""
    for attempt in range(MAX_SPECIALIST_RETRIES + 1):
        try:
            result = await runner(task, ctx)
            break
        except Exception as exc:
            last_error = str(exc)
            await event_bus.publish_json("coordinator", "retry", f"{agent}:{attempt}")
            if attempt == MAX_SPECIALIST_RETRIES:
                result = f"Agent {agent} failed after retries: {last_error}"
    if task_id:
        from tempa.core.task_store import update_subtask

        status = "failed" if "failed after retries" in result else "completed"
        update_subtask(task_id, agent, status)
    return result


async def execute_waves_node(state: CoordinatorState) -> dict[str, Any]:
    subtasks = state.get("subtasks") or []
    if not subtasks:
        return {}

    waves = compute_execution_waves(subtasks)
    results = dict(state.get("results") or {})
    context = dict(state.get("context") or {})
    user_message = state.get("user_message", "")
    task_id = state.get("task_id", "")

    for wave_index, wave in enumerate(waves):
        await event_bus.publish_json("coordinator", "wave", f"wave {wave_index + 1}/{len(waves)}")
        context["specialist_results"] = results
        coros = [
            _run_specialist_with_retry(
                str(task.get("agent")),
                str(task.get("task", "")),
                context,
                user_message,
                task_id,
            )
            for task in wave
        ]
        wave_results = await asyncio.gather(*coros)
        for task, result in zip(wave, wave_results):
            agent = str(task.get("agent"))
            results[agent] = result
            context[f"{agent}_result"] = result

    return {"results": results, "context": context}


async def merge_node(state: CoordinatorState) -> dict[str, Any]:
    await event_bus.publish_json("coordinator", "merge", "combining specialist outputs")
    if state.get("task_id"):
        from tempa.core.task_store import complete_task

        complete_task(state["task_id"])

    context = state.get("context") or {}
    stream_sink = context.get("stream_sink")
    if stream_sink:
        response, sources = await merge_results_stream(
            state["user_message"],
            state.get("results", {}),
            context,
            on_token=stream_sink,
        )
    else:
        response, sources = await merge_results(
            state["user_message"],
            state.get("results", {}),
            context,
        )
    from tempa.rag.ingest import ingest_text

    ingest_text(response, tool="core", source="coordinator", tags=["reply"])
    all_sources = list(state.get("sources") or [])
    rag_sources = context.get("rag_sources") or []
    for source in rag_sources:
        if source not in all_sources:
            all_sources.append(source)
    for source in sources:
        if source not in all_sources:
            all_sources.append(source)
    return {"response": response, "sources": all_sources}


async def channel_followup_node(state: CoordinatorState) -> dict[str, Any]:
    """After merge: notify WhatsApp when Meet was scheduled and user wanted messaging."""
    context = state.get("context") or {}
    results = state.get("results") or {}
    meet_result = results.get("meet", "")
    lower_msg = state.get("user_message", "").lower()
    wants_message = any(k in lower_msg for k in ("whatsapp", "message", "text", "notify", "send"))
    if (
        context.get("channel") == "whatsapp"
        and meet_result
        and wants_message
        and "channel" not in results
    ):
        number = context.get("whatsapp_number", "")
        if number:
            from tempa.channels.whatsapp.outbound import send_whatsapp_message

            draft = state.get("response") or meet_result
            await send_whatsapp_message(number, draft[:3500], source_channel="whatsapp_auto_reply")
            await event_bus.publish_json("channel", "meet_followup", meet_result[:120])
    return {}


def build_coordinator_graph():
    graph = StateGraph(CoordinatorState)
    graph.add_node("plan", plan_node)
    graph.add_node("plan_preview", plan_preview_node)
    graph.add_node("rag_gate", rag_gate_node)
    graph.add_node("execute_waves", execute_waves_node)
    graph.add_node("merge", merge_node)
    graph.add_node("channel_followup", channel_followup_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "plan_preview")
    graph.add_conditional_edges("plan_preview", route_after_preview, {"end": END, "rag_gate": "rag_gate"})
    graph.add_edge("rag_gate", "execute_waves")
    graph.add_edge("execute_waves", "merge")
    graph.add_edge("merge", "channel_followup")
    graph.add_edge("channel_followup", END)
    return graph.compile()


_graph = None


def get_coordinator_graph():
    global _graph
    if _graph is None:
        _graph = build_coordinator_graph()
    return _graph


async def run_coordinator_full(user_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = get_coordinator_graph()
    state = await graph.ainvoke(
        {
            "user_message": user_message,
            "context": context or {},
            "subtasks": [],
            "results": {},
            "sources": [],
        }
    )
    return {
        "response": state.get("response", ""),
        "sources": state.get("sources") or [],
        "paused": bool(state.get("paused")),
    }


async def run_coordinator_streaming(
    user_message: str,
    context: dict[str, Any] | None = None,
    on_token: Any = None,
) -> dict[str, Any]:
    ctx = dict(context or {})
    if on_token is not None:
        ctx["stream_sink"] = on_token
    return await run_coordinator_full(user_message, ctx)


async def run_coordinator(user_message: str, context: dict[str, Any] | None = None) -> str:
    result = await run_coordinator_full(user_message, context)
    return result.get("response", "")
