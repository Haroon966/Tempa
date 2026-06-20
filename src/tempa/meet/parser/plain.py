"""Parser for plain text transcripts."""

from __future__ import annotations

import re

from tempa.meet.parser.base import TranscriptParser, Utterance

SPEAKER_SPLIT_RE = re.compile(r"^(?P<speaker>[^:]{1,80}):\s*(?P<text>.+)$")


class PlainTextParser(TranscriptParser):
    """Parse newline-delimited plain text transcript exports."""

    def parse(self, content: str) -> list[Utterance]:
        """Parse plain text into utterances with optional speaker names."""
        utterances: list[Utterance] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = SPEAKER_SPLIT_RE.match(line)
            if match:
                utterances.append(
                    Utterance(
                        speaker=match.group("speaker").strip(),
                        text=match.group("text").strip(),
                        start=None,
                    )
                )
            else:
                utterances.append(Utterance(speaker=None, text=line, start=None))
        return utterances
