from __future__ import annotations

import logging

from tempa.rag.ingest import ingest_text
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)


def maybe_write_semantic_summary(text: str, *, tool: str, source: str) -> None:
    """§6.4 semantic layer write-back for substantive content."""
    word_count = len(text.split())
    min_words = 80 if tool == "whatsapp" else 40
    if word_count < min_words:
        return
    if ":semantic" in source or ":consolidation" in source:
        return
    try:
        router = get_router()
        response = router.chat_completion(
            category="text",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract a one-paragraph semantic summary with key facts and action items:\n\n"
                        f"{text[:6000]}"
                    ),
                }
            ],
            max_tokens=256,
        )
        summary = (response.choices[0].message.content or "").strip()
        if summary:
            ingest_text(summary, tool=tool, source=f"{source}:semantic", tags=["semantic"])
    except Exception:
        logger.debug("Semantic write-back skipped", exc_info=True)
