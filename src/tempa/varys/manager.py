from __future__ import annotations

import json
from typing import Any


def build_dispatch_prompt(events: list[dict[str, Any]]) -> str:
    lines = ["Process the following harness events:"]
    for ev in events:
        payload = ev.get("payload") or {}
        lines.append(
            f"- [{ev.get('source')}] {ev.get('type')}: {json.dumps(payload, ensure_ascii=False)[:800]}"
        )
    lines.append(
        "Follow plan-first protocol: if implementation is required, outline a plan and tests; "
        "do not write code until the owner approves."
    )
    return "\n".join(lines)


def is_go_signal(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"go", "approve", "proceed", "yes", "lgtm", "ship it"}


def is_work_request(text: str) -> bool:
    lowered = (text or "").lower()
    triggers = ("fix ", "implement ", "add ", "build ", "refactor ", "debug ", "investigate ")
    return any(lowered.startswith(t) for t in triggers) or " in " in lowered and "repo" in lowered
