"""Parser for Tempa meeting JSONL transcript files."""

from __future__ import annotations

import json

from tempa.meet.parser.base import TranscriptParser, Utterance


class JSONLParser(TranscriptParser):
    """Parse JSONL transcript exports (one segment object per line)."""

    def parse(self, content: str) -> list[Utterance]:
        utterances: list[Utterance] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "segment":
                continue
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            speaker = row.get("speaker")
            utterances.append(
                Utterance(
                    speaker=str(speaker).strip() if speaker else None,
                    text=text,
                    start=row.get("ts_start"),
                )
            )
        return utterances
