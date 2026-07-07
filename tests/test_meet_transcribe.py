from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tempa.meet import transcribe
from tempa.meet.stt.base import TranscriptSegment


@pytest.fixture(autouse=True)
def _isolated_meetings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    meetings_dir = tmp_path / "meetings"
    meetings_dir.mkdir()
    db_path = tmp_path / "tempa.db"
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    get_settings().ensure_dirs()
    yield


def _write_wav(path: Path, *, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    import wave

    frames = int(sample_rate * duration_s)
    pcm = b"\x00\x10" * frames
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


@pytest.mark.asyncio
async def test_transcribe_meeting_audio_writes_segments(tmp_path: Path):
    from tempa.settings import get_settings

    mid = "meet-1"
    settings = get_settings()
    meeting_dir = settings.meetings_dir / mid
    audio_dir = meeting_dir / "audio"
    _write_wav(audio_dir / f"{mid}.wav", duration_s=2.0)
    (meeting_dir / "transcripts").mkdir(parents=True)
    (meeting_dir / "transcripts" / f"{mid}.jsonl").write_text(
        json.dumps({"type": "metadata", "meeting_id": mid}) + "\n",
        encoding="utf-8",
    )

    fake_segment = TranscriptSegment(
        text="Discussed project timeline",
        seq=1,
        ts_start=None,
        ts_end=None,
        speaker=None,
        is_final=True,
        confidence=None,
        lang="en",
        payload={},
    )

    with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=""):
        with patch.object(transcribe, "transcribe_pcm_to_segments", return_value=[fake_segment]):
            count = await transcribe.transcribe_meeting_audio(mid)

    assert count == 1
    transcript_path = meeting_dir / "transcripts" / f"{mid}.jsonl"
    lines = transcript_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    row = json.loads(lines[1])
    assert row["type"] == "segment"
    assert row["text"] == "Discussed project timeline"
