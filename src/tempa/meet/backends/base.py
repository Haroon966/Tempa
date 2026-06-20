"""Abstract backend interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod

from tempa.meet.models import MeetingSummary


class LLMBackend(ABC):
    """Contract for async LLM backends used by MeetingLens."""

    @abstractmethod
    async def summarise(self, transcript: str) -> MeetingSummary:
        """Summarise transcript content into a structured meeting summary."""
