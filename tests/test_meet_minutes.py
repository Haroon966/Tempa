from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_jsonl_parser_extracts_segments():
    from tempa.meet.parser.jsonl import JSONLParser

    lines = [
        json.dumps({"type": "meta", "meeting_id": "abc"}),
        json.dumps({"type": "segment", "text": "Hello team", "speaker": "Alice"}),
        json.dumps({"type": "segment", "text": "Thanks everyone", "speaker": "Bob"}),
    ]
    parser = JSONLParser()
    plain = parser.to_plain_text("\n".join(lines))
    assert "Alice: Hello team" in plain
    assert "Bob: Thanks everyone" in plain


def test_meeting_lens_accepts_jsonl():
    from tempa.meet.minutes import MeetingLens

    lens = MeetingLens(backend=AsyncMock())
    parser = lens._select_parser("meeting.jsonl")
    from tempa.meet.parser.jsonl import JSONLParser

    assert isinstance(parser, JSONLParser)


@pytest.mark.asyncio
async def test_generate_minutes_from_jsonl_transcript():
    from tempa.meet.archive import generate_minutes_from_transcript

    summary = MagicMock()
    summary.model_dump.return_value = {"tldr": "Discussed roadmap", "summary": "Roadmap review"}

    with patch("tempa.meet.archive.MeetingLens") as lens_cls:
        lens = lens_cls.return_value
        lens.run = AsyncMock(return_value=summary)
        result = await generate_minutes_from_transcript(
            '{"type":"segment","text":"We reviewed the roadmap","speaker":"Owner"}\n',
            source_name="meeting.jsonl",
        )

    assert result["tldr"] == "Discussed roadmap"
    lens.run.assert_awaited_once()
