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
    run_qa_agent,
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
    "qa": run_qa_agent,
}

MAX_SPECIALIST_RETRIES = 2

DESTRUCTIVE_AGENTS = frozenset({"pc", "gmail", "channel"})


def _check_cancelled(context: dict[str, Any]) -> None:
    from tempa.core.chat_runs import is_cancelled

    cancel_event = context.get("cancel_event")
    if is_cancelled(cancel_event):
        raise asyncio.CancelledError("Chat run cancelled")


def _pending_preview(action_id: str, action_type: str, preview: str) -> dict[str, Any]:
    return {"id": action_id, "type": action_type, "preview": preview[:500]}


def _collect_pending_actions(state: CoordinatorState) -> list[dict[str, Any]]:
    collected = list(state.get("pending_actions") or [])
    seen = {item["id"] for item in collected if item.get("id")}
    for result in (state.get("results") or {}).values():
        try:
            payload = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        action_id = payload.get("pending_action_id")
        if payload.get("status") == "pending" and action_id and action_id not in seen:
            preview = str(payload.get("preview") or payload.get("body") or payload.get("message") or "")
            if "subject" in payload or ("to" in payload and "@" in str(payload.get("to", ""))):
                action_type = "email_send"
            elif payload.get("number"):
                action_type = "whatsapp_send"
            elif payload.get("channel") and "text" in payload:
                action_type = "slack_send"
            else:
                action_type = "whatsapp_send"
            collected.append(_pending_preview(str(action_id), action_type, preview))
            seen.add(str(action_id))
    return collected


def _extract_artifacts(results: dict[str, str]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for agent, result in results.items():
        try:
            payload = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        if agent == "gmail" and "messages" in payload:
            artifacts.append({"type": "gmail_search", **payload})
        elif agent == "calendar" and ("upcoming" in payload or "actions" in payload):
            artifacts.append({"type": "calendar_events", **payload})
    return artifacts


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
    pending_actions: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]


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
    context = dict(state.get("context") or {})
    _check_cancelled(context)
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

    from tempa.core.cross_channel_conversation import enrich_conversation_context

    context = enrich_conversation_context(context)

    subtasks = plan_subtasks(state["user_message"], context)
    from tempa.agents.tool_policy import filter_subtasks

    subtasks = filter_subtasks(subtasks, context)
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
        f"Review the plan below or open Approvals (id: {action['id'][:8]}…).\n\n"
        f"Plan:\n{plan_summary}"
    )
    return {
        "response": response,
        "paused": True,
        "pending_actions": [_pending_preview(action["id"], "plan_preview", plan_summary)],
    }


def route_after_preview(state: CoordinatorState) -> str:
    if state.get("paused"):
        return "end"
    return "rag_gate"


async def rag_gate_node(state: CoordinatorState) -> dict[str, Any]:
    """FR-CORE-04: Agentic RAG runs before specialist actions."""
    context = dict(state.get("context") or {})
    _check_cancelled(context)
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
    subtask_id: str = "",
) -> str:
    import time

    runner = AGENT_RUNNERS.get(agent)
    if not runner:
        return f"Unknown agent: {agent}"
    ctx = dict(context)
    ctx["user_message"] = user_message
    step_id = subtask_id or agent
    started = time.monotonic()
    await event_bus.publish_step(step_id, agent, "start", task[:120])
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
    duration_ms = int((time.monotonic() - started) * 1000)
    status = "error" if "failed after retries" in result else "done"
    await event_bus.publish_step(step_id, agent, status, result[:120], duration_ms=duration_ms)
    if task_id:
        from tempa.core.task_store import update_subtask

        subtask_status = "failed" if status == "error" else "completed"
        update_subtask(task_id, agent, subtask_status)
    return result


async def execute_waves_node(state: CoordinatorState) -> dict[str, Any]:
    subtasks = state.get("subtasks") or []
    if not subtasks:
        return {}

    context = dict(state.get("context") or {})
    _check_cancelled(context)
    waves = compute_execution_waves(subtasks)
    results = dict(state.get("results") or {})
    user_message = state.get("user_message", "")
    task_id = state.get("task_id", "")

    for wave_index, wave in enumerate(waves):
        _check_cancelled(context)
        await event_bus.publish_json("coordinator", "wave", f"wave {wave_index + 1}/{len(waves)}")
        context["specialist_results"] = results
        coros = [
            _run_specialist_with_retry(
                str(task.get("agent")),
                str(task.get("task", "")),
                context,
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


async def _run_langgraph_coordinator_full(
    user_message: str, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    graph = get_coordinator_graph()
    state = await graph.ainvoke(
        {
            "user_message": user_message,
            "context": context or {},
            "subtasks": [],
            "results": {},
            "sources": [],
            "pending_actions": [],
            "artifacts": [],
        }
    )
    artifacts = list(state.get("artifacts") or [])
    for artifact in _extract_artifacts(state.get("results") or {}):
        if artifact not in artifacts:
            artifacts.append(artifact)
    return {
        "response": state.get("response", ""),
        "sources": state.get("sources") or [],
        "paused": bool(state.get("paused")),
        "pending_actions": _collect_pending_actions(state),
        "artifacts": artifacts,
    }


def _is_coordinator_owner(context: dict[str, Any]) -> bool:
    from tempa.settings import get_settings
    from tempa.varys.config import load_varys_config

    channel = str(context.get("channel") or "dashboard")
    settings = get_settings()
    if channel == "slack":
        cfg = load_varys_config()
        owner_id = cfg.owner_slack_user_id or settings.slack_owner_user_id
        slack_user = str(context.get("slack_user_id") or "")
        return bool(owner_id and slack_user == owner_id)
    if channel == "whatsapp":
        owner = (settings.whatsapp_owner_number or "").strip()
        sender = str(context.get("whatsapp_number") or context.get("from_number") or "")
        return bool(owner and sender and owner in sender)
    return channel == "dashboard"


async def _emit_harness_go_signal(ctx: dict[str, Any], user_message: str) -> dict[str, Any]:
    from tempa.varys import harness

    channel = str(ctx.get("channel") or "dashboard")
    thread_ts = str(ctx.get("slack_thread_ts") or ctx.get("thread_ts") or "")
    db = harness.get_db()
    try:
        origin = f"{ctx.get('slack_channel_id', channel)}-{thread_ts or 'main'}"
        entity_id = harness.register_entity(db, channel, origin, "thread")
        harness.insert_event(
            db,
            event_id=f"{channel}-go-{thread_ts or 'main'}-{user_message[:20]}",
            source=channel,
            event_type="message.go_signal",
            context_key=entity_id,
            payload={"thread_ts": thread_ts, "channel": ctx.get("slack_channel_id", channel)},
            priority="high",
        )
    finally:
        db.close()
    return {
        "response": "Approved — I'll proceed with the plan on the next orchestrator tick.",
        "sources": [],
        "paused": False,
        "pending_actions": [],
        "artifacts": [],
    }


async def _try_go_signal_approval(
    user_message: str, context: dict[str, Any] | None
) -> dict[str, Any] | None:
    from tempa.varys.manager import is_go_signal

    if not is_go_signal(user_message):
        return None

    ctx = dict(context or {})
    if not _is_coordinator_owner(ctx):
        return {
            "response": "Only the owner can approve with go/approve.",
            "sources": [],
            "paused": False,
            "pending_actions": [],
            "artifacts": [],
        }

    from tempa.core.pending_actions import execute_pending_action, list_pending_actions

    channel = str(ctx.get("channel") or "dashboard")
    pending = list_pending_actions(status="pending")
    channel_pending = [a for a in pending if a.get("source_channel") == channel]
    candidates = channel_pending or pending
    if candidates:
        action = candidates[0]
        result = await execute_pending_action(action["id"])
        title = action.get("title") or action.get("type") or "action"
        if result.get("status") == "executed":
            exec_result = result.get("result") or {}
            if isinstance(exec_result, dict) and exec_result.get("response"):
                reply = str(exec_result["response"])
            else:
                reply = f"Approved and executed: {title}"
            return {
                "response": reply,
                "sources": [],
                "paused": False,
                "pending_actions": [],
                "artifacts": [],
            }
        reason = result.get("reason") or "unknown error"
        return {
            "response": f"Approval failed: {reason}",
            "sources": [],
            "paused": False,
            "pending_actions": [],
            "artifacts": [],
        }

    return await _emit_harness_go_signal(ctx, user_message)


def _should_use_varys(user_message: str, context: dict[str, Any] | None) -> bool:
    from tempa.settings import get_settings
    from tempa.varys.manager import is_go_signal, is_work_request

    mode = (get_settings().tempa_coordinator or "langgraph").strip().lower()
    if mode == "langgraph":
        return False
    if mode == "varys":
        return True
    # hybrid
    ctx = context or {}
    if is_go_signal(user_message) or is_work_request(user_message):
        return True
    if ctx.get("varys_dispatch") or ctx.get("force_varys"):
        return True
    lowered = user_message.lower()
    coding_hints = ("fix ", "implement", "refactor", "pr ", "github", "code", "repo", "ticket")
    if any(h in lowered for h in coding_hints):
        return True
    from tempa.agents.intent import wants_calendar, wants_gmail_full

    if wants_gmail_full(user_message) or wants_calendar(user_message):
        return False
    return False


async def run_coordinator_full(user_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    go_result = await _try_go_signal_approval(user_message, context)
    if go_result is not None:
        return go_result
    if _should_use_varys(user_message, context):
        from tempa.varys.coordinator import run_varys_coordinator

        return await run_varys_coordinator(user_message, context)
    return await _run_langgraph_coordinator_full(user_message, context)


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
