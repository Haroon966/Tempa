from __future__ import annotations

import logging
from typing import Any

from tempa.core.events import event_bus

logger = logging.getLogger(__name__)
from tempa.agents.graph import collect_pending_from_results
from tempa.orchestrator.actor_loop import needs_pause, run_actor_loop, should_use_actor_loop
from tempa.orchestrator.config import load_orchestrator_config
from tempa.orchestrator.delegate import delegate_tasks
from tempa.orchestrator.format import format_response_for_channel, guest_blocked_message
from tempa.orchestrator.goal_check import check_goal_satisfied
from tempa.orchestrator.merge import merge_worker_results, merge_with_claude
from tempa.orchestrator.planner import plan_orchestrator_tasks
from tempa.orchestrator.step_verify import results_for_merge
from tempa.orchestrator.understand import understand_user_goal
from tempa.skills.matcher import match_skills
from tempa.skills.routing import skill_routing_hints


def _resolve_merge_backend(context: dict[str, Any], override: str | None) -> str:
    if override:
        return override
    cfg = load_orchestrator_config()
    from tempa.orchestrator.routing import should_use_claude_merge

    message = str(context.get("_original_message") or context.get("user_message") or "")
    if should_use_claude_merge(message, context):
        return "claude"
    return cfg.merge_backend


async def _verify_merged_response(
    user_message: str,
    response: str,
    results: dict[str, str],
    context: dict[str, Any],
) -> str:
    from tempa.agents.specialists import _build_merge_prompt_async
    from tempa.router.verifier import verify_reply

    _, pack, _ = await _build_merge_prompt_async(
        user_message, results, context, list(context.get("rag_sources") or [])
    )
    ok, verified = verify_reply(response, pack)
    return verified if not ok else response


async def _merge_response(
    user_message: str,
    results: dict[str, str],
    ctx: dict[str, Any],
    *,
    merge_backend: str | None,
    runtime_prefetch: str,
) -> tuple[str, list[dict[str, Any]]]:
    backend = _resolve_merge_backend(ctx, merge_backend)
    rag_sources = list(ctx.get("rag_sources") or [])

    if backend == "claude":
        try:
            response = await merge_with_claude(
                user_message, results, ctx, system_extra=runtime_prefetch
            )
            response = await _verify_merged_response(user_message, response, results, ctx)
            return response, rag_sources
        except RuntimeError as exc:
            err = str(exc)
            if "Claude" not in err and "claude" not in err:
                raise
            logger.warning("Claude merge unavailable, falling back to Groq: %s", exc)

    stream_sink = ctx.get("stream_sink")
    response, merge_sources = await merge_worker_results(
        user_message,
        results,
        ctx,
        on_token=stream_sink,
    )
    sources = list(rag_sources)
    for source in merge_sources:
        if source not in sources:
            sources.append(source)
    return response, sources


class OrchestratorAgent:
    async def _channel_followup(
        self,
        user_message: str,
        results: dict[str, str],
        response: str,
        context: dict[str, Any],
    ) -> None:
        meet_result = results.get("meet", "")
        lower_msg = user_message.lower()
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

                draft = response or meet_result
                await send_whatsapp_message(number, draft, source_channel="whatsapp_auto_reply")
                await event_bus.publish_json("channel", "meet_followup", meet_result[:120])

    async def run(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
        *,
        merge_backend: str | None = None,
        runtime_prefetch: str = "",
    ) -> dict[str, Any]:
        from tempa.core.cross_channel_conversation import enrich_conversation_context

        ctx = enrich_conversation_context(dict(context or {}))
        ctx["user_message"] = user_message
        ctx["_original_message"] = user_message

        blocked = guest_blocked_message(user_message, ctx)
        if blocked:
            return {
                "response": format_response_for_channel(blocked, ctx),
                "sources": [],
                "paused": False,
                "pending_actions": [],
                "artifacts": [],
                "planned_steps": [],
            }

        user_goal = await understand_user_goal(user_message, ctx)
        ctx["user_goal"] = user_goal
        missing = [m for m in user_goal.get("missing_info") or [] if str(m).strip()]
        if missing and not ctx.get("plan_approved"):
            question = "Before I proceed: " + "; ".join(str(m) for m in missing) + "?"
            return {
                "response": format_response_for_channel(question, ctx),
                "sources": [],
                "paused": False,
                "pending_actions": [],
                "artifacts": [],
                "planned_steps": [],
            }

        skills = match_skills(user_message, ctx)
        ctx["matched_skills"] = [s.name for s in skills]
        ctx["skill_routing"] = skill_routing_hints(skills)

        await event_bus.publish_json(
            "orchestrator",
            "plan",
            f"skills={[s.name for s in skills]}",
        )

        subtasks = plan_orchestrator_tasks(user_message, ctx)
        others = [t for t in subtasks if t.get("agent") != "rag"]
        rag_task = next((t for t in subtasks if t.get("agent") == "rag"), None)
        planned_steps = [
            {"agent": t.get("agent"), "task": str(t.get("task", ""))[:120]} for t in subtasks if t.get("agent") != "rag"
        ]

        from tempa.core.task_store import create_task

        task_id = create_task(user_message, others) if others else ""

        results: dict[str, str] = {}
        paused = False
        pending_actions: list[dict[str, Any]] = []
        clarification: str | None = None

        if rag_task:
            from tempa.agents.graph import _run_specialist_with_retry

            rag_result = await _run_specialist_with_retry(
                "rag",
                str(rag_task.get("task", user_message)),
                ctx,
                user_message,
                task_id,
                "rag",
            )
            results["rag"] = rag_result
            ctx["rag_context"] = rag_result
            rag_sources = ctx.get("rag_sources") or []
        else:
            rag_sources = []

        if others:
            if should_use_actor_loop(subtasks, ctx):
                results, ctx, paused, pending_actions, clarification = await run_actor_loop(
                    user_message,
                    subtasks,
                    ctx,
                    task_id=task_id,
                    existing_results=results,
                )
                planned_steps = ctx.get("planned_steps") or planned_steps
            else:
                worker_results, ctx, clarification = await delegate_tasks(
                    user_message,
                    others,
                    ctx,
                    task_id=task_id,
                    existing_results=results,
                )
                results.update(worker_results)
                planned_steps = ctx.get("planned_steps") or planned_steps
                pending_actions = collect_pending_from_results(results)
                paused = needs_pause(pending_actions)

        if clarification:
            return {
                "response": format_response_for_channel(clarification.strip(), ctx),
                "sources": list(rag_sources),
                "paused": False,
                "pending_actions": pending_actions,
                "artifacts": [],
                "planned_steps": planned_steps,
            }

        merge_results_dict = results_for_merge(ctx, results)

        goal = await check_goal_satisfied(user_message, user_goal, ctx)
        extra_runs = 0
        from tempa.agents.config import goal_check_max_extra_steps

        while (
            not goal.get("satisfied")
            and goal.get("extra_steps")
            and extra_runs < goal_check_max_extra_steps()
            and not paused
        ):
            extra_runs += 1
            await event_bus.publish_json("orchestrator", "activity", "goal_replan")
            extra_steps = list(goal.get("extra_steps") or [])
            results, ctx, extra_paused, extra_pending, extra_clarify = await run_actor_loop(
                user_message,
                extra_steps,
                ctx,
                task_id=task_id,
                existing_results=results,
                queue_override=extra_steps,
            )
            merge_results_dict = results_for_merge(ctx, results)
            if extra_paused:
                paused = True
                pending_actions.extend(extra_pending)
            if extra_clarify:
                return {
                    "response": format_response_for_channel(extra_clarify.strip(), ctx),
                    "sources": list(rag_sources),
                    "paused": False,
                    "pending_actions": pending_actions,
                    "artifacts": [],
                    "planned_steps": planned_steps,
                }
            goal = await check_goal_satisfied(user_message, user_goal, ctx)

        response, sources = await _merge_response(
            user_message,
            merge_results_dict,
            ctx,
            merge_backend=merge_backend,
            runtime_prefetch=runtime_prefetch,
        )

        if not goal.get("satisfied") and goal.get("gaps"):
            gaps = str(goal.get("gaps") or "").strip()
            if gaps and gaps.lower() not in response.lower():
                response = f"{response.strip()}\n\n_Note: {gaps}_"

        response = format_response_for_channel(response.strip(), ctx)

        from tempa.rag.ingest import ingest_text

        ingest_text(response, tool="core", source="orchestrator", tags=["reply"])

        await self._channel_followup(user_message, merge_results_dict, response, ctx)

        from tempa.agents.graph import _extract_artifacts

        artifacts: list[dict[str, Any]] = []
        for artifact in _extract_artifacts(merge_results_dict):
            if artifact not in artifacts:
                artifacts.append(artifact)

        if task_id:
            from tempa.core.task_store import complete_task

            complete_task(task_id)

        if not pending_actions:
            pending_actions = collect_pending_from_results(merge_results_dict)
        if not paused:
            paused = needs_pause(pending_actions)

        try:
            from tempa.learning.loop import schedule_after_turn

            schedule_after_turn(
                user_message,
                success=bool(goal.get("satisfied")) and not paused,
                paused=paused,
                matched_skills=list(ctx.get("matched_skills") or []),
                planned_steps=planned_steps,
                response=response,
                notes="orchestrator",
                context=ctx,
            )
        except Exception:
            pass

        return {
            "response": response,
            "sources": sources,
            "paused": paused,
            "pending_actions": pending_actions,
            "artifacts": artifacts,
            "planned_steps": planned_steps,
        }


_agent: OrchestratorAgent | None = None


def get_orchestrator() -> OrchestratorAgent:
    global _agent
    if _agent is None:
        from tempa.orchestrator.hooks_impl import register_all_hooks

        register_all_hooks()
        _agent = OrchestratorAgent()
    return _agent


async def run_orchestrator(
    user_message: str,
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return await get_orchestrator().run(user_message, context, **kwargs)
