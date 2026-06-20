from __future__ import annotations

import json

from tempa.meet.backends.base import LLMBackend
from tempa.meet.models import BackendError, MeetingSummary
from tempa.router.groq_router import get_router

SYSTEM_PROMPT = (
    "You are a meeting analysis assistant. Return only valid JSON matching the "
    "MeetingSummary schema. Keep fields concise, factual, and grounded in transcript text."
)

USER_PROMPT_TEMPLATE = """Analyse this meeting transcript and produce JSON that matches exactly this schema:
{schema}

Transcript:
{transcript}
"""


class GroqBackend(LLMBackend):
    """Summarise transcripts via Groq chat completions."""

    def __init__(self, category: str = "reasoning") -> None:
        self.category = category
        self.router = get_router()

    async def summarise(self, transcript: str) -> MeetingSummary:
        schema_text = json.dumps(MeetingSummary.model_json_schema(), indent=2)
        prompt = USER_PROMPT_TEMPLATE.format(schema=schema_text, transcript=transcript)

        import asyncio

        def _call() -> str:
            response = self.router.chat_completion(
                category=self.category,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=4096,
            )
            return response.choices[0].message.content or "{}"

        try:
            content = await asyncio.to_thread(_call)
            payload = json.loads(content)
            return MeetingSummary.model_validate(payload)
        except Exception as exc:
            raise BackendError(f"Groq summarisation failed: {exc}") from exc
