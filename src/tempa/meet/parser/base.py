"""Base parser interfaces and data structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Utterance:
    """Single parsed utterance from a transcript."""

    speaker: str | None
    text: str
    start: str | None


class TranscriptParser(ABC):
    """Abstract parser for transcript content."""

    @abstractmethod
    def parse(self, content: str) -> list[Utterance]:
        """Parse raw transcript content into utterances."""

    def to_plain_text(self, content: str) -> str:
        """Render utterances as plain lines for LLM input."""
        utterances = self.parse(content)
        lines: list[str] = []
        for utterance in utterances:
            prefix = f"{utterance.speaker}: " if utterance.speaker else ""
            lines.append(f"{prefix}{utterance.text}")
        return "\n".join(lines)
