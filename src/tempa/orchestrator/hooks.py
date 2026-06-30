from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

HookFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]

# Pre-orchestrator hooks run in order; first non-None result short-circuits planning.
PRE_HOOK_ORDER: list[str] = [
    "go_signal",
    "jira_ticket",
    "clarification",
    "varys_work_request",
    "jira_direct",
    "slack_direct",
]

_HOOKS: dict[str, HookFn] = {}


def register_pre_hook(name: str, fn: HookFn) -> None:
    _HOOKS[name] = fn


def list_pre_hooks() -> list[str]:
    return [name for name in PRE_HOOK_ORDER if name in _HOOKS]


async def run_pre_hooks(user_message: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    from tempa.orchestrator.config import load_orchestrator_config

    cfg = load_orchestrator_config()
    if not cfg.pre_hooks_enabled:
        return None
    ctx = dict(context or {})
    for name in PRE_HOOK_ORDER:
        fn = _HOOKS.get(name)
        if fn is None:
            continue
        result = await fn(user_message, ctx)
        if result is not None:
            return result
    return None
