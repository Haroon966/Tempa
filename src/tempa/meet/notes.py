from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)


def _read_transcript_text(path: Path) -> str:
    if not path.exists():
        return ""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if row.get("type") == "segment" and row.get("text"):
            speaker = row.get("speaker") or "Unknown"
            lines.append(f"{speaker}: {row['text']}")
    return "\n".join(lines)


async def live_notes_loop(transcript_path: Path, notes_path: Path, stop_event: asyncio.Event, interval_s: int = 60) -> None:
    """Periodically summarize growing transcript into running meeting notes."""
    last_len = 0
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    router = get_router()
    while not stop_event.is_set():
        await asyncio.sleep(interval_s)
        text = _read_transcript_text(transcript_path)
        if len(text) <= last_len + 40:
            continue
        last_len = len(text)
        prompt = (
            "You are taking live meeting notes. Update a concise running summary with key points, "
            "decisions, and action items so far.\n\nTranscript so far:\n"
            f"{text[-12000:]}"
        )
        try:
            response = router.chat_completion(
                category="reasoning",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            notes = response.choices[0].message.content or ""
            notes_path.write_text(notes, encoding="utf-8")
            await asyncio.sleep(0)
        except Exception:
            logger.exception("Live notes update failed")
