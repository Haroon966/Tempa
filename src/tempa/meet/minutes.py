"""Core orchestrator for transcript parsing and summarisation."""

from __future__ import annotations

from pathlib import Path

from tempa.meet.backends.base import LLMBackend
from tempa.meet.models import MeetingSummary, ParseError
from tempa.meet.parser.base import TranscriptParser
from tempa.meet.parser.jsonl import JSONLParser
from tempa.meet.parser.plain import PlainTextParser
from tempa.meet.parser.srt import SRTParser
from tempa.meet.parser.vtt import VTTParser


class MeetingLens:
    """Parse transcript files and produce structured summaries through a backend."""

    def __init__(self, backend: LLMBackend) -> None:
        """Initialize with a configured LLM backend instance."""
        self.backend = backend

    async def run(self, transcript_content: str, source_name: str | None = None) -> MeetingSummary:
        """Parse transcript content and request a structured summary from the backend."""
        parser = self._select_parser(source_name)
        plain_text = parser.to_plain_text(transcript_content)
        return await self.backend.summarise(plain_text)

    def _select_parser(self, source_name: str | None) -> TranscriptParser:
        """Select parser by filename extension, defaulting to plain text."""
        if not source_name or source_name == "-":
            return PlainTextParser()
        suffix = Path(source_name).suffix.lower()
        if suffix == ".vtt":
            return VTTParser()
        if suffix == ".srt":
            return SRTParser()
        if suffix == ".txt":
            return PlainTextParser()
        if suffix == ".jsonl":
            return JSONLParser()
        raise ParseError(f"Unsupported transcript format '{suffix}'. Supported: .txt, .vtt, .srt, .jsonl")
