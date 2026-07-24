from __future__ import annotations

import json
import logging
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from tempa.meet.audio_convert import resolve_audio_path
from tempa.settings import get_settings

_logger = logging.getLogger(__name__)

STORYBOARD_TILE_WIDTH = 160
STORYBOARD_TILE_HEIGHT = 90
STORYBOARD_COLUMNS = 10
STORYBOARD_MAX_TILES = 60
STORYBOARD_MIN_INTERVAL = 2.0

# YouTube custom thumbs want ≥640×360; 1280×720 JPEG stays under the 2MB API cap.
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720
THUMBNAIL_NAME = "thumbnail.jpg"


def _ffprobe_ok(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", str(path)],
            capture_output=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _mp4_is_fragmented(path: Path) -> bool:
    """True for fMP4 (iso5/moof) — ffprobe passes but browsers often cannot play these."""
    if path.suffix.lower() != ".mp4" or not path.exists():
        return False
    try:
        head = path.read_bytes()[:128]
        if b"iso5" in head or b"iso6" in head:
            return True
        # ponytail: moof in first 256KB is enough to detect fragmented capture output
        return b"moof" in path.read_bytes()[:262144]
    except Exception:
        return False


def video_has_audio_stream(path: Path) -> bool:
    if not path.exists() or not shutil.which("ffprobe"):
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0 and "audio" in (result.stdout or "")
    except Exception:
        return False


def _resolve_mux_audio_path(meeting_id: str, *, audio_path_hint: str = "") -> Path | None:
    if audio_path_hint:
        candidate = Path(audio_path_hint)
        if candidate.exists() and candidate.stat().st_size > 44:
            return candidate
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    pcm = meeting_dir_for_id(meeting_id) / "audio" / f"{safe_id}.pcm"
    if pcm.exists() and pcm.stat().st_size > 44:
        return pcm
    return resolve_audio_download_path(meeting_id, audio_path_hint=audio_path_hint)


def mux_audio_into_video(
    video_path: Path,
    audio_path: Path,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Path | None:
    """Combine a separate capture audio track into the video file for playback with sound."""
    if not shutil.which("ffmpeg"):
        return None
    if not video_path.exists() or video_path.stat().st_size <= 1024:
        return None
    if not audio_path.exists() or audio_path.stat().st_size <= 44:
        return None
    if video_has_audio_stream(video_path):
        return video_path

    suffix = video_path.suffix.lower()
    merged = video_path.with_name(f"{video_path.stem}_avmux{video_path.suffix}")
    audio_codec = "libopus" if suffix == ".webm" else "aac"
    audio_input: list[str]
    if audio_path.suffix.lower() == ".pcm":
        audio_input = [
            "-f",
            "s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-i",
            str(audio_path),
        ]
    else:
        audio_input = ["-i", str(audio_path)]

    for video_codec in ("copy", "libx264"):
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            *audio_input,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            video_codec,
            "-c:a",
            audio_codec,
            "-shortest",
        ]
        if video_codec == "libx264":
            cmd.extend(["-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"])
        if audio_codec == "aac":
            cmd.extend(["-b:a", "128k"])
        if suffix == ".mp4":
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(merged))

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
        except Exception:
            _logger.exception("GMEET: audio mux failed video=%s audio=%s", video_path, audio_path)
            return None

        if result.returncode == 0 and merged.exists() and merged.stat().st_size > 1024:
            merged.replace(video_path)
            _logger.info("GMEET: muxed audio into video video=%s audio=%s codec=%s", video_path, audio_path, video_codec)
            _invalidate_storyboard_cache_for_video(video_path)
            return video_path

        _logger.warning(
            "GMEET: audio mux attempt failed video=%s codec=%s stderr=%s",
            video_path,
            video_codec,
            (result.stderr or b"").decode(errors="replace")[:300],
        )

    if merged.exists():
        merged.unlink(missing_ok=True)
    return None


def ensure_video_includes_audio(meeting_id: str, *, audio_path_hint: str = "") -> Path | None:
    """Mux captured meeting audio into the video file when they were recorded separately."""
    video_path = resolve_video_path(meeting_id)
    if not video_path or not video_path.exists():
        return None
    if video_has_audio_stream(video_path):
        return video_path
    audio_path = _resolve_mux_audio_path(meeting_id, audio_path_hint=audio_path_hint)
    if not audio_path:
        return video_path
    return mux_audio_into_video(video_path, audio_path) or video_path


def _invalidate_storyboard_cache_for_video(video_path: Path) -> None:
    video_dir = video_path.parent
    for name in ("storyboard.jpg", "storyboard.json"):
        (video_dir / name).unlink(missing_ok=True)


def finalize_meeting_media_files(meeting_id: str, *, audio_path_hint: str = "") -> dict[str, bool]:
    """Permanent post-capture step: embed audio in video and remux MP4 for browser playback."""
    result = {
        "has_video": False,
        "video_has_audio": False,
        "audio_muxed": False,
        "video_ready": False,
    }
    video_path = resolve_video_path(meeting_id)
    if not video_path or not video_path.exists():
        return result

    result["has_video"] = True
    had_audio = video_has_audio_stream(video_path)
    video_path = ensure_video_includes_audio(meeting_id, audio_path_hint=audio_path_hint) or video_path
    if not had_audio and video_has_audio_stream(video_path):
        result["audio_muxed"] = True

    result["video_has_audio"] = video_has_audio_stream(video_path)

    if video_path.suffix.lower() == ".mp4":
        finalized = finalize_mp4_for_playback(video_path)
        result["video_ready"] = bool(finalized or _ffprobe_ok(video_path))
    else:
        result["video_ready"] = video_path.stat().st_size > 50_000

    # Poster lives next to video/ so it survives delete_local_meeting_video.
    if result["has_video"]:
        ensure_meeting_thumbnail(meeting_id, video_path=video_path)

    return result


def finalize_mp4_for_playback(path: Path) -> Path | None:
    """Remux MP4 so browsers can play it (moov atom at file start)."""
    if not path.exists() or path.stat().st_size < 1024:
        return None
    if _ffprobe_ok(path) and not _mp4_is_fragmented(path):
        return path

    fixed = path.with_name(f"{path.stem}_fixed{path.suffix}")
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(fixed),
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            _logger.warning(
                "GMEET: mp4 remux failed path=%s stderr=%s",
                path,
                (result.stderr or b"").decode(errors="replace")[:300],
            )
            return None
        if fixed.exists() and _ffprobe_ok(fixed):
            fixed.replace(path)
            return path
    except Exception:
        _logger.exception("GMEET: mp4 finalize failed path=%s", path)
    return None


def meeting_dir_for_id(meeting_id: str) -> Path:
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    return get_settings().meetings_dir / safe_id


def resolve_transcript_path(meeting_id: str) -> Path | None:
    meeting_dir = meeting_dir_for_id(meeting_id)
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    path = meeting_dir / "transcripts" / f"{safe_id}.jsonl"
    return path if path.exists() else None


def resolve_video_path(meeting_id: str) -> Path | None:
    meeting_dir = meeting_dir_for_id(meeting_id)
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    video_dir = meeting_dir / "video"
    if not video_dir.exists():
        return None
    preferred_mp4 = video_dir / f"{safe_id}.mp4"
    if preferred_mp4.exists():
        return preferred_mp4
    preferred_webm = video_dir / f"{safe_id}.webm"
    if preferred_webm.exists():
        return preferred_webm
    for pattern in ("*.mp4", "*.webm"):
        files = sorted(video_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def resolve_playable_video_path(meeting_id: str, *, audio_path_hint: str = "") -> Path | None:
    """Return a browser-playable video path; runs one-time media finalization if needed."""
    finalize_meeting_media_files(meeting_id, audio_path_hint=audio_path_hint)
    path = resolve_video_path(meeting_id)
    if not path or not path.exists():
        return None
    if path.suffix.lower() == ".mp4":
        if _ffprobe_ok(path):
            return path
        if path.stat().st_size > 50_000:
            return path
        return None
    if path.stat().st_size > 50_000:
        return path
    return None


def delete_local_meeting_video(meeting_id: str) -> bool:
    """Remove the local video directory once the recording lives on YouTube.

    Audio, transcript, and meeting-root thumbnail.jpg are kept (email/YouTube poster).
    """
    video_dir = meeting_dir_for_id(meeting_id) / "video"
    if not video_dir.exists():
        return False
    try:
        shutil.rmtree(video_dir)
        _logger.info("GMEET: removed local video for %s (uploaded to YouTube)", meeting_id)
        return True
    except Exception:
        _logger.exception("GMEET: failed to remove local video meeting=%s", meeting_id)
        return False


def meeting_thumbnail_path(meeting_id: str) -> Path:
    return meeting_dir_for_id(meeting_id) / THUMBNAIL_NAME


def resolve_meeting_thumbnail_path(meeting_id: str) -> Path | None:
    path = meeting_thumbnail_path(meeting_id)
    if path.exists() and path.stat().st_size > 1000:
        return path
    return None


def load_meeting_thumbnail_bytes(meeting_id: str) -> bytes | None:
    path = resolve_meeting_thumbnail_path(meeting_id)
    if not path:
        return None
    try:
        data = path.read_bytes()
        return data if len(data) > 1000 else None
    except OSError:
        return None


def ensure_meeting_thumbnail(
    meeting_id: str,
    *,
    video_path: Path | None = None,
) -> Path | None:
    """Extract a 16:9 JPEG poster from the recording for YouTube + email CID."""
    existing = resolve_meeting_thumbnail_path(meeting_id)
    if existing:
        return existing

    path = video_path
    if path is None or not path.exists():
        path = resolve_video_path(meeting_id)
    if path is None or not path.exists() or path.stat().st_size < 1024:
        return None
    if not shutil.which("ffmpeg"):
        return None

    dest = meeting_thumbnail_path(meeting_id)
    dest.parent.mkdir(parents=True, exist_ok=True)

    duration = video_duration_seconds(path)
    if duration > 3:
        seek = min(max(duration * 0.15, 1.0), duration - 1.0)
    elif duration > 0:
        seek = max(duration * 0.5, 0.0)
    else:
        seek = 0.0

    scale = (
        f"scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:(ow-iw)/2:(oh-ih)/2"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{seek:.3f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-vf",
        scale,
        str(dest),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        if result.returncode != 0 or not dest.exists() or dest.stat().st_size < 1000:
            _logger.warning(
                "GMEET: thumbnail extract failed meeting=%s stderr=%s",
                meeting_id,
                (result.stderr or b"").decode(errors="replace")[:300],
            )
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception:
        _logger.exception("GMEET: thumbnail extract failed meeting=%s", meeting_id)
        dest.unlink(missing_ok=True)
        return None


def resolve_audio_download_path(meeting_id: str, *, audio_path_hint: str = "") -> Path | None:
    if audio_path_hint:
        candidate = Path(audio_path_hint)
        if candidate.exists() and candidate.stat().st_size > 44:
            return candidate
    path = resolve_audio_path(meeting_dir_for_id(meeting_id), meeting_id.replace("/", "_").replace("\\", "_"))
    if path and path.exists() and path.stat().st_size > 44:
        return path
    return None


def _video_has_content(path: Path | None) -> bool:
    if path is None or not path.exists() or path.stat().st_size <= 1024:
        return False
    if path.suffix.lower() == ".mp4" and shutil.which("ffprobe"):
        return _ffprobe_ok(path)
    return path.stat().st_size > 50_000


def _max_amplitude(frames: bytes, sampwidth: int) -> float:
    if not frames or sampwidth != 2:
        return 0.0
    count = len(frames) // 2
    if count <= 0:
        return 0.0
    samples = struct.unpack(f"<{count}h", frames[: count * 2])
    return float(max(abs(sample) for sample in samples))


def audio_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            if rate <= 0:
                return 0.0
            return wf.getnframes() / rate
    except Exception:
        return 0.0


def compute_audio_waveform(
    meeting_id: str,
    *,
    audio_path_hint: str = "",
    bars: int = 72,
) -> dict[str, float | list[float] | bool]:
    """Downsample meeting audio into normalized peaks for dashboard waveform UI."""
    path = resolve_audio_download_path(meeting_id, audio_path_hint=audio_path_hint)
    if path is None or not path.exists():
        return {"available": False, "duration_seconds": 0.0, "peaks": []}

    safe_bars = max(16, min(int(bars), 160))
    try:
        with wave.open(str(path), "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
            duration = nframes / framerate if framerate else 0.0
            block = max(1, nframes // safe_bars)
            peaks: list[float] = []
            for i in range(safe_bars):
                start = min(i * block, max(nframes - 1, 0))
                wf.setpos(start)
                chunk = wf.readframes(min(block, max(nframes - start, 0)))
                if not chunk:
                    peaks.append(0.0)
                    continue
                if nchannels > 1 and sampwidth == 2:
                    count = len(chunk) // 2
                    samples = struct.unpack(f"<{count}h", chunk[: count * 2])
                    mono = samples[::nchannels]
                    peaks.append(float(max(abs(sample) for sample in mono)) if mono else 0.0)
                else:
                    peaks.append(_max_amplitude(chunk, sampwidth))
    except Exception:
        _logger.exception("GMEET: waveform extraction failed meeting=%s path=%s", meeting_id, path)
        return {"available": False, "duration_seconds": 0.0, "peaks": []}

    max_peak = max(peaks) if peaks else 0.0
    if max_peak > 0:
        peaks = [round(peak / max_peak, 4) for peak in peaks]

    return {
        "available": True,
        "duration_seconds": round(duration, 2),
        "peaks": peaks,
    }


def video_duration_seconds(path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        _logger.exception("GMEET: ffprobe duration failed path=%s", path)
    return 0.0


def _storyboard_paths(meeting_id: str) -> tuple[Path, Path]:
    video_dir = meeting_dir_for_id(meeting_id) / "video"
    return video_dir / "storyboard.jpg", video_dir / "storyboard.json"


def compute_video_storyboard(meeting_id: str) -> dict[str, int | float | bool | str]:
    """Build or load a sprite sheet for timeline hover previews."""
    sprite_path, manifest_path = _storyboard_paths(meeting_id)
    if sprite_path.exists() and manifest_path.exists():
        try:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            if cached.get("available"):
                return cached
        except Exception:
            _logger.exception("GMEET: storyboard manifest read failed meeting=%s", meeting_id)

    path = resolve_playable_video_path(meeting_id)
    if path is None or not path.exists():
        return {"available": False}

    if not shutil.which("ffmpeg"):
        return {"available": False}

    duration = video_duration_seconds(path)
    if duration <= 0:
        return {"available": False}

    interval = max(STORYBOARD_MIN_INTERVAL, duration / STORYBOARD_MAX_TILES)
    count = min(STORYBOARD_MAX_TILES, max(1, int(duration / interval) + 1))
    columns = STORYBOARD_COLUMNS
    rows = max(1, (count + columns - 1) // columns)

    sprite_path.parent.mkdir(parents=True, exist_ok=True)
    scale = (
        f"scale={STORYBOARD_TILE_WIDTH}:{STORYBOARD_TILE_HEIGHT}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={STORYBOARD_TILE_WIDTH}:{STORYBOARD_TILE_HEIGHT}:(ow-iw)/2:(oh-ih)/2"
    )
    vf = f"fps=1/{interval:.3f},{scale},tile={columns}x{rows}"
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vf",
                vf,
                "-frames:v",
                "1",
                str(sprite_path),
            ],
            capture_output=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0 or not sprite_path.exists():
            _logger.warning(
                "GMEET: storyboard generation failed meeting=%s stderr=%s",
                meeting_id,
                (result.stderr or b"").decode(errors="replace")[:300],
            )
            return {"available": False}
    except Exception:
        _logger.exception("GMEET: storyboard generation failed meeting=%s", meeting_id)
        return {"available": False}

    manifest: dict[str, int | float | bool | str] = {
        "available": True,
        "duration_seconds": round(duration, 2),
        "interval_seconds": round(interval, 2),
        "tile_width": STORYBOARD_TILE_WIDTH,
        "tile_height": STORYBOARD_TILE_HEIGHT,
        "columns": columns,
        "rows": rows,
        "count": count,
        "sprite_url": f"/api/meetings/{meeting_id}/storyboard/sprite",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def resolve_storyboard_sprite_path(meeting_id: str) -> Path | None:
    sprite_path, _ = _storyboard_paths(meeting_id)
    return sprite_path if sprite_path.exists() else None


def list_meeting_media(meeting_id: str, *, audio_path_hint: str = "") -> dict[str, str | bool | float]:
    """Describe downloadable media for API + dashboard."""
    base = f"/api/meetings/{meeting_id}"
    audio = resolve_audio_download_path(meeting_id, audio_path_hint=audio_path_hint)
    video = resolve_video_path(meeting_id)
    transcript = resolve_transcript_path(meeting_id)
    duration_seconds = round(audio_duration_seconds(audio), 2) if audio else 0.0
    playable_video = resolve_playable_video_path(meeting_id) if _video_has_content(video) else None
    video_duration = round(video_duration_seconds(playable_video), 2) if playable_video else 0.0
    return {
        "has_audio": audio is not None,
        "has_video": _video_has_content(video),
        "has_transcript": transcript is not None,
        "audio_url": f"{base}/audio" if audio else "",
        "video_url": f"{base}/video" if _video_has_content(video) else "",
        "transcript_url": f"{base}/transcript" if transcript else "",
        "duration_seconds": duration_seconds,
        "video_duration_seconds": video_duration,
        "storyboard_url": f"{base}/storyboard" if _video_has_content(video) else "",
    }
