from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_varys_coordinator(
    user_message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Legacy entry — delegates to unified OrchestratorAgent with Claude merge."""
    from tempa.orchestrator.hooks import run_pre_hooks
    from tempa.orchestrator.hooks_impl import register_all_hooks
    from tempa.orchestrator.agent import run_orchestrator

    register_all_hooks()
    hook_result = await run_pre_hooks(user_message, context)
    if hook_result is not None:
        return hook_result

    ctx = dict(context or {})
    ctx["force_varys"] = True
    return await run_orchestrator(user_message, ctx, merge_backend="claude")
