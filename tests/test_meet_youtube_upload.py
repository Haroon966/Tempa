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
    thumb = tmp_path / "thumbnail.jpg"
    thumb.write_bytes(b"J" * 2000)

    mock_request = MagicMock()
    mock_request.next_chunk.return_value = (None, {"id": "vid999"})
    mock_insert = MagicMock(return_value=mock_request)
    mock_thumb_set = MagicMock(return_value=MagicMock(execute=MagicMock(return_value={})))
    mock_youtube = MagicMock()
    mock_youtube.videos.return_value.insert = mock_insert
    mock_youtube.thumbnails.return_value.set = mock_thumb_set

    monkeypatch.setattr(youtube_upload, "load_youtube_credentials", lambda: object())
    monkeypatch.setattr(youtube_upload, "build", lambda *a, **k: mock_youtube)

    result = youtube_upload.upload_meeting_video(
        video,
        title="Demo",
        description="desc",
        privacy="unlisted",
        thumbnail_path=thumb,
    )
    assert result["youtube_video_id"] == "vid999"
    assert result["youtube_url"] == "https://youtu.be/vid999"
    assert result["confirmed"] is True
    assert result["thumbnail_set"] is True
    body = mock_insert.call_args.kwargs["body"]
    assert body["status"]["privacyStatus"] == "unlisted"
    mock_thumb_set.assert_called_once()
    assert mock_thumb_set.call_args.kwargs["videoId"] == "vid999"


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


def test_maybe_upload_skips_empty_segments(monkeypatch):
    monkeypatch.setenv("MEET_YOUTUBE_UPLOAD_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    result = maybe_upload_meeting_to_youtube(
        "meet-empty",
        "Title",
        segment_count=0,
        humans_seen=False,
    )
    assert result == {"status": "skipped_empty", "confirmed": False}


def test_maybe_upload_allows_when_segments(monkeypatch, tmp_path):
    monkeypatch.setenv("MEET_YOUTUBE_UPLOAD_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 60_000)

    with patch("tempa.meet.youtube_upload.resolve_playable_video_path", return_value=video):
        with patch("tempa.meet.youtube_upload.load_youtube_credentials", return_value=object()):
            with patch(
                "tempa.meet.media.ensure_meeting_thumbnail",
                return_value=tmp_path / "thumbnail.jpg",
            ):
                with patch(
                    "tempa.meet.youtube_upload.upload_meeting_video",
                    return_value={
                        "youtube_video_id": "v1",
                        "youtube_url": "https://youtu.be/v1",
                        "status": "uploaded",
                        "confirmed": True,
                        "thumbnail_set": True,
                    },
                ) as upload:
                    result = maybe_upload_meeting_to_youtube(
                        "meet-ok",
                        "Title",
                        segment_count=3,
                        humans_seen=True,
                    )
    assert result and result["youtube_video_id"] == "v1"
    upload.assert_called_once()
    assert upload.call_args.kwargs.get("thumbnail_path") == tmp_path / "thumbnail.jpg"


def test_meeting_is_uploadable():
    from tempa.meet.quality import meeting_is_uploadable

    assert meeting_is_uploadable(segment_count=1) is True
    assert meeting_is_uploadable(segment_count=0) is False


def test_delete_local_meeting_video_removes_video_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MEET_YOUTUBE_UPLOAD_ENABLED", "true")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    from tempa.meet import media

    meeting_dir = get_settings().meetings_dir / "meet-del"
    video_dir = meeting_dir / "video"
    video_dir.mkdir(parents=True)
    (video_dir / "meet-del.mp4").write_bytes(b"x" * 60_000)
    audio_dir = meeting_dir / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "keep.wav").write_bytes(b"y")
    thumb = meeting_dir / "thumbnail.jpg"
    thumb.write_bytes(b"J" * 2000)

    assert media.delete_local_meeting_video("meet-del") is True
    assert not video_dir.exists()
    assert (audio_dir / "keep.wav").exists()
    assert thumb.exists()
    assert media.delete_local_meeting_video("meet-del") is False
