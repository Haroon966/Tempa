from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def check_goal_satisfied(
    user_message: str,
    user_goal: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Stage 4–5: check whether execution satisfied the user goal."""
    from tempa.agents.config import goal_check_enabled, goal_check_max_extra_steps

    if not goal_check_enabled():
        return {"satisfied": True, "gaps": "", "extra_steps": []}

    step_results = context.get("step_results") or []
    if not step_results:
        return {"satisfied": True, "gaps": "", "extra_steps": []}

    errors = [
        s
        for s in step_results
        if isinstance(s, dict)
        and isinstance(s.get("payload"), dict)
        and s["payload"].get("status") == "error"
    ]
    if errors:
        agent = str(errors[-1].get("agent") or "worker")
        reason = str((errors[-1].get("payload") or {}).get("reason") or "failed")
        return {
            "satisfied": False,
            "gaps": f"{agent} failed: {reason}",
            "extra_steps": [],
        }

    from tempa.agents.config import model_category_for_agent
    from tempa.router.groq_router import get_router

    router = get_router()
    prompt = (
        "Did the worker steps satisfy the user's goal?\n"
        'Return JSON only: {"satisfied": true|false, "gaps": "...", '
        '"extra_steps": [{"agent":"...","task":"...","depends_on":[]}]}\n'
        f"extra_steps: at most {goal_check_max_extra_steps()} follow-up step if clearly needed; else []\n"
        f"User goal: {json.dumps(user_goal, ensure_ascii=False)}\n"
        f"User message: {user_message}\n"
        f"Step results: {json.dumps(step_results, ensure_ascii=False)[:3000]}"
    )
    try:
        response = router.chat_completion(
            category=model_category_for_agent("coordinator", "reasoning"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.1,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        if isinstance(data, dict):
            extra = list(data.get("extra_steps") or [])[: goal_check_max_extra_steps()]
            return {
                "satisfied": bool(data.get("satisfied", True)),
                "gaps": str(data.get("gaps") or ""),
                "extra_steps": extra,
            }
    except Exception as exc:
        logger.warning("goal_check failed: %s", exc)

    return {"satisfied": True, "gaps": "", "extra_steps": []}
