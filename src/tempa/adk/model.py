"""Groq via ADK LiteLLM bridge."""

from __future__ import annotations

import os

from google.adk.models.lite_llm import LiteLlm

# Matches config/groq_models.yaml text chain default.
_DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def groq_litellm(*, model: str | None = None) -> LiteLlm:
    from tempa.settings import get_settings

    settings = get_settings()
    if settings.groq_api_key:
        os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
    name = (model or _DEFAULT_GROQ_MODEL).strip()
    if not name.startswith("groq/"):
        name = f"groq/{name}"
    return LiteLlm(model=name)
