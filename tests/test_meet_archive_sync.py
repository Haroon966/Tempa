from __future__ import annotations

import json
from pathlib import Path

import pytest

from tempa.meet import archive


@pytest.fixture(autouse=True)
def _isolated_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    meetings_dir = tmp_path / "meetings"
    meetings_dir.mkdir()
    db_path = tmp_path / "tempa.db"
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_dirs()
    yield


@pytest.mark.asyncio
async def test_archive_meeting_from_disk_indexes_transcript(tmp_path: Path):
    from tempa.settings import get_settings

    settings = get_settings()
    mid = "abc-123"
    meeting_dir = settings.meetings_dir / mid
    transcript_dir = meeting_dir / "transcripts"
    transcript_dir.mkdir(parents=True)
    transcript_path = transcript_dir / f"{mid}.jsonl"
    transcript_path.write_text(
        json.dumps({"type": "segment", "speaker": "Alex", "text": "Hello team"}) + "\n",
        encoding="utf-8",
    )
    (meeting_dir / "manifest.json").write_text(
        json.dumps({"title": "Standup", "meet_link": "https://meet.google.com/abc-defg-hij"}),
        encoding="utf-8",
    )

    ok = await archive.archive_meeting_from_disk(mid)
    assert ok is True

    meetings = await archive.list_meetings()
    assert len(meetings) == 1
    assert meetings[0]["title"] == "Standup"
    assert meetings[0]["minutes_status"] == "partial"
    assert meetings[0]["artifacts"]["transcript"] is True


@pytest.mark.asyncio
async def test_sync_meeting_archives_from_disk_skips_empty_dirs(tmp_path: Path):
    from tempa.settings import get_settings

    settings = get_settings()
    (settings.meetings_dir / "empty-meeting").mkdir()
    synced = await archive.sync_meeting_archives_from_disk()
    assert synced == 0
    assert await archive.list_meetings() == []
