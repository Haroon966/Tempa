"""Map Cursor SDK stream events → Tempa IDE-like activity lines."""

from __future__ import annotations

import re
from typing import Any

_CURSOR_BRAND_RE = re.compile(r"\bcursor\b|\bgroq\b|\bsdk\b", re.I)
_FATAL_RE = re.compile(r"fatal:|Traceback|TimeoutError|CursorAgentError", re.I)


def _scrub(text: str) -> str:
    text = " ".join((text or "").split())
    if _FATAL_RE.search(text):
        return ""
    text = _CURSOR_BRAND_RE.sub("agent", text)
    return text[:220].strip()


def scrub_outbound_text(text: str) -> str:
    """Strip brand leaks and raw internals from final Slack posts."""
    if not text or not str(text).strip():
        return text
    lines: list[str] = []
    for line in str(text).splitlines():
        if _FATAL_RE.search(line):
            continue
        lines.append(_CURSOR_BRAND_RE.sub("agent", line))
    out = "\n".join(lines).strip()
    return out or "_Something went wrong — please ask again._"

def step_from_sdk_message(msg: Any) -> str | None:
    """Return a short Tempa activity step, or None to skip."""
    mtype = getattr(msg, "type", None) or getattr(msg, "kind", None) or ""
    mtype = str(mtype).lower()

    # Tool use
    if "tool" in mtype:
        name = ""
        for attr in ("name", "tool_name", "toolName"):
            if hasattr(msg, attr):
                name = str(getattr(msg, attr) or "")
                break
        payload = getattr(msg, "message", None) or msg
        if not name and isinstance(payload, dict):
            name = str(payload.get("name") or payload.get("tool_name") or "")
        content = getattr(msg, "content", None)
        if not name and content:
            name = str(content)[:80]
        name = _scrub(name.replace("_", " ").replace(".", " "))
        if not name:
            return "Using a tool…"
        return f"Using {name}…"

    if "assistant" in mtype or mtype in ("text", "message"):
        text = ""
        message = getattr(msg, "message", None)
        if message is not None:
            blocks = getattr(message, "content", None) or []
            bits: list[str] = []
            for block in blocks:
                btype = getattr(block, "type", "") or (block.get("type") if isinstance(block, dict) else "")
                if str(btype) == "text":
                    bits.append(str(getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "") or ""))
                elif "tool" in str(btype).lower():
                    tname = getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else "")
                    if tname:
                        return f"Using {str(tname).replace('_', ' ')}…"
            text = " ".join(bits)
        if not text:
            text = str(getattr(msg, "text", None) or getattr(msg, "content", None) or "")
        text = _scrub(text)
        if not text or len(text) < 8:
            return None
        # First sentence-ish as a thinking step
        short = text.split(".")[0].strip()
        if len(short) > 120:
            short = short[:117] + "…"
        return short

    if "thinking" in mtype:
        return "Thinking…"

    if "status" in mtype:
        status = _scrub(str(getattr(msg, "status", None) or getattr(msg, "text", None) or ""))
        return status or None

    return None


def merge_steps(steps: list[str], new: str | None, *, max_steps: int = 12) -> list[str]:
    if not new:
        return steps
    if steps and steps[-1] == new:
        return steps
    out = list(steps) + [new]
    return out[-max_steps:]
