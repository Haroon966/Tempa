"""Closed self-improvement loop — Hermes-style skill create/refine + memory nudge."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from tempa.learning.store import (
    append_skill_section,
    is_immutable,
    llm_json,
    read_skill_path,
    record_skill_usage,
    write_skill_md,
)

logger = logging.getLogger(__name__)


def self_improve_enabled() -> bool:
    from tempa.settings import get_settings

    return bool(getattr(get_settings(), "tempa_self_improve", True))


def schedule_after_turn(
    user_message: str,
    *,
    success: bool,
    paused: bool = False,
    matched_skills: list[str] | None = None,
    planned_steps: list[Any] | None = None,
    response: str = "",
    notes: str = "",
    context: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget learning so user replies are not blocked."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run() -> None:
        try:
            await after_turn(
                user_message,
                success=success,
                paused=paused,
                matched_skills=matched_skills,
                planned_steps=planned_steps,
                response=response,
                notes=notes,
                context=context,
            )
        except Exception:
            logger.debug("schedule_after_turn failed", exc_info=True)

    loop.create_task(_run(), name="tempa-self-improve")


async def after_turn(
    user_message: str,
    *,
    success: bool,
    paused: bool = False,
    matched_skills: list[str] | None = None,
    planned_steps: list[Any] | None = None,
    response: str = "",
    notes: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run after a coordinator turn. Safe to call in a background task."""
    if not self_improve_enabled():
        return {"skipped": True, "reason": "disabled"}

    matched = [str(s) for s in (matched_skills or []) if str(s).strip()]
    steps = planned_steps or []
    outcome = {
        "recorded_usage": False,
        "created_skill": None,
        "refined_skills": [],
        "memory_writes": 0,
    }

    try:
        record_skill_usage(matched, success=success and not paused)
        outcome["recorded_usage"] = bool(matched)
    except Exception:
        logger.debug("record_skill_usage failed", exc_info=True)

    # Complex successful plans → create reusable skill
    if success and not paused and len(steps) >= 2:
        created = await _maybe_create_skill(user_message, steps, response, notes)
        if created:
            outcome["created_skill"] = created

    # Matched skills → refine from success/failure
    if matched:
        refined = await _maybe_refine_skills(
            user_message,
            matched,
            success=success and not paused,
            response=response,
            steps=steps,
        )
        outcome["refined_skills"] = refined

    # Memory nudge: persist durable facts from corrections / preferences in the turn
    try:
        writes = await _memory_nudge(user_message, response, context or {})
        outcome["memory_writes"] = writes
    except Exception:
        logger.debug("memory nudge failed", exc_info=True)

    # Also keep hermes draft trail for promote API
    try:
        from tempa.hermes.skills_bridge import record_plan_outcome

        record_plan_outcome(
            user_message,
            success=success and not paused,
            notes=notes or "self_improve",
            planned_steps=steps,
        )
    except Exception:
        pass

    return outcome


async def _maybe_create_skill(
    user_message: str,
    steps: list[Any],
    response: str,
    notes: str,
) -> str | None:
    agents = []
    for step in steps:
        if isinstance(step, dict) and step.get("agent"):
            agents.append(str(step["agent"]))
        elif isinstance(step, str):
            agents.append(step)
    agents = list(dict.fromkeys(agents))

    prompt = (
        "You are Tempa's learning loop. Decide if this successful multi-step task should "
        "become a reusable SKILL.md for future similar requests.\n"
        "Do NOT create skills for one-off greetings, pure coding/PR work, or secrets.\n"
        "Return JSON only:\n"
        '{"should_create": bool, "name": "kebab-slug", "description": "...", '
        '"triggers": ["phrase", ...], "workers": ["gmail","calendar",...], '
        '"body": "markdown playbook", "skip_reason": "..."}\n\n'
        f"User message: {user_message[:400]}\n"
        f"Steps: {agents}\n"
        f"Notes: {notes[:200]}\n"
        f"Reply excerpt: {response[:500]}\n"
    )
    data = llm_json(prompt)
    if not data.get("should_create"):
        return None
    name = str(data.get("name") or "").strip()
    body = str(data.get("body") or "").strip()
    triggers = data.get("triggers") if isinstance(data.get("triggers"), list) else []
    workers = data.get("workers") if isinstance(data.get("workers"), list) else agents
    if not name or not body or not triggers:
        return None
    if is_immutable(name):
        return None
    path = write_skill_md(
        name,
        description=str(data.get("description") or name),
        triggers=[str(t) for t in triggers],
        workers=[str(w) for w in workers],
        body=body,
        priority=25,
    )
    logger.info("Self-improve: created skill %s at %s", name, path)
    return name


async def _maybe_refine_skills(
    user_message: str,
    matched: list[str],
    *,
    success: bool,
    response: str,
    steps: list[Any],
) -> list[str]:
    refined: list[str] = []
    for name in matched[:3]:
        path = read_skill_path(name)
        if not path or is_immutable(name, str(path)):
            continue
        try:
            current = path.read_text(encoding="utf-8")[:2500]
        except OSError:
            continue
        prompt = (
            "You refine an existing Tempa skill after a real turn.\n"
            "Return JSON only:\n"
            '{"should_refine": bool, "triggers_add": ["..."], "section": "markdown to append", '
            '"skip_reason": "..."}\n'
            "Only refine when it will help future similar requests. Keep section short.\n"
            f"Outcome: {'success' if success else 'failure'}\n"
            f"User message: {user_message[:300]}\n"
            f"Current skill:\n{current}\n"
            f"Reply excerpt: {response[:400]}\n"
        )
        data = llm_json(prompt, max_tokens=400)
        if not data.get("should_refine"):
            continue
        section = str(data.get("section") or "").strip()
        triggers_add = data.get("triggers_add") if isinstance(data.get("triggers_add"), list) else []
        if section:
            append_skill_section(path, section)
        if triggers_add:
            _merge_triggers(path, [str(t) for t in triggers_add])
        refined.append(name)
        logger.info("Self-improve: refined skill %s", name)
    return refined


def _merge_triggers(path: Path, extra: list[str]) -> None:
    import re

    import yaml

    from tempa.learning.store import is_immutable

    if is_immutable(path.parent.name, str(path)):
        return
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text.strip() + "\n", re.DOTALL)
    if not match:
        return
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        return
    triggers = [str(t).lower() for t in (meta.get("triggers") or [])]
    for t in extra:
        tl = t.lower().strip()
        if tl and tl not in triggers:
            triggers.append(tl)
    meta["triggers"] = triggers[:16]
    from tempa.learning.store import yaml_dump_frontmatter

    new_text = f"---\n{yaml_dump_frontmatter(meta)}---\n\n{match.group(2).strip()}\n"
    path.write_text(new_text, encoding="utf-8")
    try:
        from tempa.skills.loader import reload_skills

        reload_skills()
    except Exception:
        pass


async def _memory_nudge(user_message: str, response: str, context: dict[str, Any]) -> int:
    """Extract durable preference/correction/fact from the turn into procedural memory."""
    lower = user_message.lower()
    # Cheap gate: only nudge on corrective / preference language
    if not any(
        k in lower
        for k in (
            "remember",
            "always",
            "never",
            "prefer",
            "from now on",
            "actually",
            "don't",
            "do not",
            "wrong",
        )
    ):
        return 0

    prompt = (
        "Extract durable memory for Tempa. Return JSON only:\n"
        '{"items": [{"kind": "preference"|"correction"|"fact"|"person"|"project"|"decision", '
        '"text": "..."}]}\n'
        "Empty items if nothing durable. No secrets.\n"
        f"User: {user_message[:400]}\n"
        f"Assistant: {response[:400]}\n"
    )
    data = llm_json(prompt, max_tokens=350)
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if not items:
        return 0
    from tempa.rag.procedural import add_durable

    written = 0
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "fact")
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            add_durable(text, kind=kind, source="self_improve")
            written += 1
        except Exception:
            logger.debug("add_durable failed", exc_info=True)
    return written
