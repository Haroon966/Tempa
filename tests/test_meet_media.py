from pathlib import Path
import json
import struct
import subprocess
import wave

from tempa.meet.media import (
    _mp4_is_fragmented,
    compute_audio_waveform,
    compute_video_storyboard,
    finalize_meeting_media_files,
    list_meeting_media,
    resolve_storyboard_sprite_path,
    resolve_video_path,
    video_has_audio_stream,
)


def _write_test_wav(path: Path, *, frames: int = 8000, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        samples = [int(16000 * (0.5 if (i // 100) % 2 == 0 else 0.1)) for i in range(frames)]
        wf.writeframes(struct.pack(f"<{frames}h", *samples))


def test_list_meeting_media_flags(tmp_path, monkeypatch):
    meeting_id = "abc-123"
    safe_id = meeting_id
    meeting_dir = tmp_path / safe_id
    (meeting_dir / "audio").mkdir(parents=True)
    _write_test_wav(meeting_dir / "audio" / f"{safe_id}.wav")
    (meeting_dir / "video").mkdir(parents=True)
    (meeting_dir / "video" / f"{safe_id}.webm").write_bytes(b"webm" + b"\0" * 60_000)
    (meeting_dir / "transcripts").mkdir(parents=True)
    (meeting_dir / "transcripts" / f"{safe_id}.jsonl").write_text(
        '{"type":"metadata"}\n{"type":"segment","text":"hi"}\n',
        encoding="utf-8",
    )

    class _Settings:
        meetings_dir = tmp_path

    monkeypatch.setattr("tempa.meet.media.get_settings", lambda: _Settings())

    media = list_meeting_media(meeting_id)
    assert media["has_audio"] is True
    assert media["has_video"] is True
    assert media["has_transcript"] is True
    assert media["audio_url"].endswith("/audio")
    assert media["video_url"].endswith("/video")
    assert media["transcript_url"].endswith("/transcript")
    assert media["duration_seconds"] == 1.0
    assert media["storyboard_url"].endswith("/storyboard")


def test_storyboard_manifest_cache(tmp_path, monkeypatch):
    meeting_id = "story-1"
    safe_id = meeting_id
    video_dir = tmp_path / safe_id / "video"
    video_dir.mkdir(parents=True)
    sprite = video_dir / "storyboard.jpg"
    manifest = video_dir / "storyboard.json"
    sprite.write_bytes(b"fake-image")
    manifest.write_text(
        json.dumps(
            {
                "available": True,
                "duration_seconds": 120.0,
                "interval_seconds": 5.0,
                "tile_width": 160,
                "tile_height": 90,
                "columns": 10,
                "rows": 2,
                "count": 12,
                "sprite_url": f"/api/meetings/{meeting_id}/storyboard/sprite",
            }
        ),
        encoding="utf-8",
    )

    class _Settings:
        meetings_dir = tmp_path

    monkeypatch.setattr("tempa.meet.media.get_settings", lambda: _Settings())
    monkeypatch.setattr("tempa.meet.media.resolve_playable_video_path", lambda _mid: None)

    result = compute_video_storyboard(meeting_id)
    assert result["available"] is True
    assert result["count"] == 12
    assert resolve_storyboard_sprite_path(meeting_id) == sprite


def test_compute_audio_waveform(tmp_path, monkeypatch):
    meeting_id = "wave-1"
    safe_id = meeting_id
    meeting_dir = tmp_path / safe_id
    _write_test_wav(meeting_dir / "audio" / f"{safe_id}.wav", frames=16000, rate=8000)

    class _Settings:
        meetings_dir = tmp_path

    monkeypatch.setattr("tempa.meet.media.get_settings", lambda: _Settings())

    result = compute_audio_waveform(meeting_id, bars=32)
    assert result["available"] is True
    assert result["duration_seconds"] == 2.0
    assert len(result["peaks"]) == 32
    assert max(result["peaks"]) == 1.0


def test_video_has_audio_stream_false_without_ffprobe(tmp_path):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"fake")
    assert video_has_audio_stream(video) is False


def test_mux_audio_skips_when_video_already_has_audio(tmp_path, monkeypatch):
    from tempa.meet.media import mux_audio_into_video, video_has_audio_stream

    video = tmp_path / "clip.mp4"
    audio = tmp_path / "clip.pcm"
    video.write_bytes(b"v" * 2000)
    audio.write_bytes(b"a" * 2000)
    monkeypatch.setattr("tempa.meet.media.video_has_audio_stream", lambda _path: True)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "tempa.meet.media.subprocess.run",
        lambda *args, **kwargs: calls.append(list(args[0])) or subprocess.CompletedProcess(args[0], 0),
    )
    assert mux_audio_into_video(video, audio) == video
    assert calls == []


def test_ensure_video_includes_audio_muxes_when_needed(tmp_path, monkeypatch):
    from tempa.meet.media import ensure_video_includes_audio

    meeting_id = "mux-1"
    safe_id = meeting_id
    meeting_dir = tmp_path / safe_id
    video = meeting_dir / "video" / f"{safe_id}.mp4"
    pcm = meeting_dir / "audio" / f"{safe_id}.pcm"
    video.parent.mkdir(parents=True)
    pcm.parent.mkdir(parents=True)
    video.write_bytes(b"v" * 2000)
    pcm.write_bytes(b"a" * 2000)

    class _Settings:
        meetings_dir = tmp_path

    monkeypatch.setattr("tempa.meet.media.get_settings", lambda: _Settings())
    monkeypatch.setattr("tempa.meet.media.video_has_audio_stream", lambda _path: False)
    monkeypatch.setattr("tempa.meet.media.shutil.which", lambda _cmd: "/usr/bin/ffmpeg")

    def fake_run(cmd, **kwargs):
        out = video.with_name(f"{video.stem}_avmux{video.suffix}")
        out.write_bytes(b"m" * 2000)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("tempa.meet.media.subprocess.run", fake_run)
    result = ensure_video_includes_audio(meeting_id)
    assert result == video
    assert video.read_bytes() == b"m" * 2000


def test_finalize_meeting_media_files_reports_mux(tmp_path, monkeypatch):
    meeting_id = "fin-1"
    safe_id = meeting_id
    video = tmp_path / safe_id / "video" / f"{safe_id}.mp4"
    pcm = tmp_path / safe_id / "audio" / f"{safe_id}.pcm"
    video.parent.mkdir(parents=True)
    pcm.parent.mkdir(parents=True)
    video.write_bytes(b"v" * 2000)
    pcm.write_bytes(b"a" * 2000)

    class _Settings:
        meetings_dir = tmp_path

    audio_checks = iter([False, True, True])

    monkeypatch.setattr("tempa.meet.media.get_settings", lambda: _Settings())
    monkeypatch.setattr("tempa.meet.media.video_has_audio_stream", lambda _path: next(audio_checks, True))
    monkeypatch.setattr("tempa.meet.media.shutil.which", lambda _cmd: "/usr/bin/ffmpeg")
    monkeypatch.setattr("tempa.meet.media.finalize_mp4_for_playback", lambda path: path)

    def fake_run(cmd, **kwargs):
        out = video.with_name(f"{video.stem}_avmux{video.suffix}")
        out.write_bytes(b"x" * 2000)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("tempa.meet.media.subprocess.run", fake_run)

    first = finalize_meeting_media_files(meeting_id)
    assert first["has_video"] is True
    assert first["audio_muxed"] is True

    second = finalize_meeting_media_files(meeting_id)
    assert second["audio_muxed"] is False
    assert second["video_has_audio"] is True


def test_resolve_video_path_prefers_named_file(tmp_path, monkeypatch):
    meeting_id = "meet-1"
    safe_id = meeting_id
    video_dir = tmp_path / safe_id / "video"
    video_dir.mkdir(parents=True)
    older = video_dir / "older.webm"
    newer = video_dir / f"{safe_id}.webm"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")

    class _Settings:
        meetings_dir = tmp_path

    monkeypatch.setattr("tempa.meet.media.get_settings", lambda: _Settings())

    assert resolve_video_path(meeting_id) == newer


def test_mp4_is_fragmented_detects_fmp4(tmp_path):
    frag = tmp_path / "frag.mp4"
    frag.write_bytes(b"\x00" * 32 + b"ftypiso5" + b"\x00" * 80 + b"moof" + b"\x00" * 40)
    plain = tmp_path / "plain.mp4"
    plain.write_bytes(b"\x00" * 32 + b"ftypisom" + b"\x00" * 80 + b"moov" + b"\x00" * 40)
    assert _mp4_is_fragmented(frag) is True
    assert _mp4_is_fragmented(plain) is False
