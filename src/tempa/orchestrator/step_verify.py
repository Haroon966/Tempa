from __future__ import annotations

import json
import re
from typing import Any

_PLAIN_ERROR_MARKERS = (
    "not connected",
    "failed after retries",
    "unknown agent:",
    "search failed",
    "could not find",
)

_AGENT_ERROR_PATTERNS: dict[str, re.Pattern[str]] = {
    "gmail": re.compile(r"gmail.*(?:not connected|failed)", re.I),
    "calendar": re.compile(r"calendar.*not connected", re.I),
}


def parse_step_result(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def observe_step(
    context: dict[str, Any],
    agent: str,
    raw: str,
    *,
    subtask_id: str = "",
    task: str = "",
) -> dict[str, Any] | None:
    payload = parse_step_result(raw)
    facts = list(context.get("action_facts") or [])
    step_results = list(context.get("step_results") or [])

    if payload:
        status = payload.get("status")
        if status:
            line = f"[{agent}] status={status}"
            reason = payload.get("reason")
            if reason:
                line += f" reason={str(reason)[:120]}"
            facts.append(line)
        elif payload.get("messages") is not None:
            count = payload.get("count", len(payload.get("messages") or []))
            facts.append(f"[{agent}] found {count} messages")
        elif payload.get("open_findings") is not None:
            facts.append(f"[{agent}] qa findings listed")
        else:
            facts.append(f"[{agent}] completed")
    elif raw.strip():
        facts.append(f"[{agent}] {raw[:200]}")

    context["action_facts"] = facts
    entry = {
        "agent": agent,
        "subtask_id": subtask_id or agent,
        "task": task[:120] if task else "",
        "result": raw,
        "payload": payload,
    }
    step_results.append(entry)
    context["step_results"] = step_results

    specialist_results = dict(context.get("specialist_results") or {})
    specialist_results[agent] = raw
    context["specialist_results"] = specialist_results
    return payload


def verify_step(agent: str, raw: str, payload: dict[str, Any] | None) -> tuple[bool, str]:
    lower = raw.lower()
    if payload is None:
        if "failed after retries" in lower:
            return False, "specialist failed"
        for marker in _PLAIN_ERROR_MARKERS:
            if marker in lower:
                return False, raw[:160]
        pattern = _AGENT_ERROR_PATTERNS.get(agent)
        if pattern and pattern.search(raw):
            return False, raw[:160]
        if raw.strip() and not raw.strip().startswith("{"):
            if any(w in lower for w in ("error", "failed", "not connected")):
                return False, raw[:160]
        return True, ""

    status = payload.get("status")
    if status == "pending":
        return True, "pending"
    if status == "error":
        return False, str(payload.get("reason") or "error")
    if status == "disabled":
        return True, ""
    return True, ""


def results_for_merge(context: dict[str, Any], base: dict[str, str] | None = None) -> dict[str, str]:
    """Build merge results dict; last result wins per agent, includes rag from base."""
    merged = dict(base or {})
    for step in context.get("step_results") or []:
        if not isinstance(step, dict):
            continue
        agent = str(step.get("agent") or "")
        result = step.get("result")
        if agent and isinstance(result, str):
            merged[agent] = result
    return merged
