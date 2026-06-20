"""Parser for WebVTT transcripts."""

from __future__ import annotations

import re

from tempa.meet.parser.base import TranscriptParser, Utterance

TIMESTAMP_LINE_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}(?::\d{2})?\.\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}(?::\d{2})?\.\d{3})"
)
SPEAKER_LINE_RE = re.compile(r"^(?P<speaker>[^:]{1,80}):\s*(?P<text>.+)$")


class VTTParser(TranscriptParser):
    """Parse WebVTT content, including Zoom/Teams style speaker lines."""

    def parse(self, content: str) -> list[Utterance]:
        """Parse VTT into utterances with timestamps and optional speakers."""
        utterances: list[Utterance] = []
        blocks = re.split(r"\n\s*\n", content.strip())
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            if lines[0].upper() == "WEBVTT":
                continue

            cue_index = 0
            if lines[0].isdigit():
                cue_index = 1

            if cue_index >= len(lines):
                continue

            ts_match = TIMESTAMP_LINE_RE.match(lines[cue_index])
            if not ts_match:
                continue

            start = ts_match.group("start")
            payload_lines = lines[cue_index + 1 :]
            if not payload_lines:
                continue

            merged_text = " ".join(payload_lines).strip()
            speaker: str | None = None
            text = merged_text
            speaker_match = SPEAKER_LINE_RE.match(merged_text)
            if speaker_match:
                speaker = speaker_match.group("speaker").strip()
                text = speaker_match.group("text").strip()

            utterances.append(Utterance(speaker=speaker, text=text, start=start))
        return utterances
