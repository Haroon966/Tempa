from __future__ import annotations

from typing import Any

from tempa.core.events import event_bus


async def merge_worker_results(
    user_message: str,
    results: dict[str, str],
    context: dict[str, Any],
    *,
    on_token: Any = None,
) -> tuple[str, list[dict[str, Any]]]:
    from tempa.agents.specialists import merge_results, merge_results_stream
    from tempa.skills.matcher import match_skills
    from tempa.skills.prompt import format_skills_for_prompt

    ctx = dict(context)
    skills = match_skills(user_message, ctx)
    skill_block = format_skills_for_prompt(skills)
    if skill_block:
        ctx["active_skills_prompt"] = skill_block

    await event_bus.publish_json("orchestrator", "merge", "combining worker outputs")

    if on_token is not None:
        return await merge_results_stream(user_message, results, ctx, on_token=on_token)
    return await merge_results(user_message, results, ctx)


async def merge_with_claude(
    user_message: str,
    results: dict[str, str],
    context: dict[str, Any],
    *,
    system_extra: str = "",
) -> str:
    from tempa.skills.matcher import match_skills
    from tempa.skills.prompt import format_skills_for_prompt
    from tempa.varys.context import build_context
    from tempa.varys.runner import run_claude_prompt

    built = build_context(user_message, context)
    skills = match_skills(user_message, context)
    skill_block = format_skills_for_prompt(skills)
    system = built["system"]
    if skill_block:
        system += "\n\n## Active skills\n" + skill_block
    if system_extra:
        system += "\n\n## Live tool results\n" + system_extra
    if results:
        blocks = []
        for label, payload in results.items():
            blocks.append(f"## {label}\n{payload[:4000]}")
        system += "\n\n## Worker results\n" + "\n\n".join(blocks)
    return await run_claude_prompt(system=system, user=built["user"])
