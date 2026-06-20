from __future__ import annotations

import logging

from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)


def screen_outbound_message(text: str) -> tuple[bool, str]:
    """Screen outbound WhatsApp or email content with Safety GPT OSS 20B."""
    if not text.strip():
        return False, "Empty message"
    router = get_router()
    prompt = (
        "You are a safety moderator. Assess if this outbound message or email is safe to send. "
        "Block harassment, hate, explicit threats, or clearly harmful instructions. "
        "Reply with exactly one line: SAFE or UNSAFE, then a short reason.\n\n"
        f"Message:\n{text[:4000]}"
    )
    try:
        response = router.chat_completion(
            category="safety",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=128,
            temperature=0,
        )
        msg = response.choices[0].message
        content = (msg.content or "").strip()
        if not content:
            content = str(getattr(msg, "reasoning", "") or "").strip()
        if not content:
            logger.warning("Safety model returned empty verdict; allowing message")
            return True, "safety_inconclusive_allowed"

        upper = content.upper()
        if upper.startswith("SAFE") or (
            "SAFE" in upper and "UNSAFE" not in upper and "NOT SAFE" not in upper
        ):
            return True, content
        if upper.startswith("UNSAFE") or "UNSAFE" in upper:
            reason = content[6:].strip(" :-") if upper.startswith("UNSAFE") else content
            return False, reason or "flagged by safety screen"
        logger.warning("Ambiguous safety verdict %r; allowing message", content[:80])
        return True, content
    except Exception as exc:
        logger.warning("Safety screen failed, allowing message: %s", exc)
        return True, "safety_unavailable"
