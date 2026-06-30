from __future__ import annotations

import logging
from typing import Any

from tempa.core.events import event_bus

logger = logging.getLogger(__name__)
from tempa.orchestrator.config import load_orchestrator_config
from tempa.orchestrator.delegate import delegate_tasks
from tempa.orchestrator.format import format_response_for_channel, guest_blocked_message
from tempa.orchestrator.merge import merge_worker_results, merge_with_claude
from tempa.orchestrator.planner import plan_orchestrator_tasks
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

        from tempa.core.task_store import create_task

        task_id = create_task(user_message, others) if others else ""

        results: dict[str, str] = {}
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
            worker_results, ctx = await delegate_tasks(
                user_message,
                others,
                ctx,
                task_id=task_id,
                existing_results=results,
            )
            results.update(worker_results)

        backend = _resolve_merge_backend(ctx, merge_backend)

        if backend == "claude":
            try:
                response = await merge_with_claude(
                    user_message, results, ctx, system_extra=runtime_prefetch
                )
                sources = list(rag_sources)
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
        else:
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

        response = format_response_for_channel(response.strip(), ctx)

        from tempa.rag.ingest import ingest_text

        ingest_text(response, tool="core", source="orchestrator", tags=["reply"])

        await self._channel_followup(user_message, results, response, ctx)

        from tempa.agents.graph import _extract_artifacts

        artifacts: list[dict[str, Any]] = []
        for artifact in _extract_artifacts(results):
            if artifact not in artifacts:
                artifacts.append(artifact)

        if task_id:
            from tempa.core.task_store import complete_task

            complete_task(task_id)

        return {
            "response": response,
            "sources": sources,
            "paused": False,
            "pending_actions": [],
            "artifacts": artifacts,
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
