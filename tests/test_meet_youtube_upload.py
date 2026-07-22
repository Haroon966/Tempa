from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tempa.meet.youtube_upload import (
    build_upload_body,
    maybe_upload_meeting_to_youtube,
    validate_youtube_privacy,
)


def test_validate_youtube_privacy_rejects_public():
    with pytest.raises(ValueError, match="private or unlisted"):
        validate_youtube_privacy("public")


def test_validate_youtube_privacy_accepts_unlisted():
    assert validate_youtube_privacy("unlisted") == "unlisted"


def test_build_upload_body_uses_unlisted_privacy():
    body = build_upload_body(title="Standup", description="notes", privacy="unlisted")
    assert body["status"]["privacyStatus"] == "unlisted"
    assert body["snippet"]["title"] == "Standup"


def test_maybe_upload_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("MEET_YOUTUBE_UPLOAD_ENABLED", "false")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    assert maybe_upload_meeting_to_youtube("meet-1", "Title") is None


def test_maybe_upload_skips_when_already_uploaded(monkeypatch, tmp_path):
    monkeypatch.setenv("MEET_YOUTUBE_UPLOAD_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    meeting_dir = settings.meetings_dir / "meet-1"
    meeting_dir.mkdir(parents=True)
    (meeting_dir / "manifest.json").write_text(
        '{"youtube_video_id": "abc123"}',
        encoding="utf-8",
    )

    result = maybe_upload_meeting_to_youtube("meet-1", "Title")
    assert result == {
        "youtube_video_id": "abc123",
        "youtube_url": "https://youtu.be/abc123",
        "status": "skipped",
    }


def test_maybe_upload_skips_without_video(monkeypatch, tmp_path):
    monkeypatch.setenv("MEET_YOUTUBE_UPLOAD_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    with patch("tempa.meet.youtube_upload.resolve_playable_video_path", return_value=None):
        assert maybe_upload_meeting_to_youtube("meet-2", "Title") is None


def test_upload_meeting_video_calls_insert_with_body(monkeypatch, tmp_path):
    from tempa.meet import youtube_upload

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 60_000)

    mock_request = MagicMock()
    mock_request.next_chunk.return_value = (None, {"id": "vid999"})
    mock_insert = MagicMock(return_value=mock_request)
    mock_youtube = MagicMock()
    mock_youtube.videos.return_value.insert = mock_insert

    monkeypatch.setattr(youtube_upload, "load_youtube_credentials", lambda: object())
    monkeypatch.setattr(youtube_upload, "build", lambda *a, **k: mock_youtube)

    result = youtube_upload.upload_meeting_video(
        video,
        title="Demo",
        description="desc",
        privacy="unlisted",
    )
    assert result["youtube_video_id"] == "vid999"
    assert result["youtube_url"] == "https://youtu.be/vid999"
    assert result["confirmed"] is True
    body = mock_insert.call_args.kwargs["body"]
    assert body["status"]["privacyStatus"] == "unlisted"


def test_upload_not_confirmed_when_status_failed(monkeypatch, tmp_path):
    from tempa.meet import youtube_upload

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 60_000)

    mock_request = MagicMock()
    mock_request.next_chunk.return_value = (None, {"id": "vid999", "status": {"uploadStatus": "failed"}})
    mock_youtube = MagicMock()
    mock_youtube.videos.return_value.insert.return_value = mock_request

    monkeypatch.setattr(youtube_upload, "load_youtube_credentials", lambda: object())
    monkeypatch.setattr(youtube_upload, "build", lambda *a, **k: mock_youtube)

    result = youtube_upload.upload_meeting_video(
        video, title="Demo", description="desc", privacy="unlisted"
    )
    assert result["confirmed"] is False


def test_delete_local_meeting_video_removes_video_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MEET_YOUTUBE_UPLOAD_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    from tempa.meet import media

    video_dir = get_settings().meetings_dir / "meet-del" / "video"
    video_dir.mkdir(parents=True)
    (video_dir / "meet-del.mp4").write_bytes(b"x" * 60_000)
    audio_dir = get_settings().meetings_dir / "meet-del" / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "keep.wav").write_bytes(b"y")

    assert media.delete_local_meeting_video("meet-del") is True
    assert not video_dir.exists()
    assert (audio_dir / "keep.wav").exists()
    assert media.delete_local_meeting_video("meet-del") is False
