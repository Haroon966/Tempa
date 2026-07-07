from __future__ import annotations

import json
import logging
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.meet.archive import _parse_transcript_jsonl
from tempa.meet.audio_capture import is_silent_capture, pcm16_peak_rms
from tempa.meet.audio_convert import resolve_audio_path
from tempa.meet.media import resolve_video_path
from tempa.meet.stt.groq_whisper import GroqWhisperAdapter
from tempa.meet.stt.base import TranscriptSegment
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def _load_pcm_bytes(audio_path: Path) -> tuple[bytes, int]:
    if audio_path.suffix.lower() == ".wav":
        with wave.open(str(audio_path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                raise ValueError(f"Unsupported WAV format: {audio_path}")
            sample_rate = wf.getframerate()
            return wf.readframes(wf.getnframes()), sample_rate
    if audio_path.suffix.lower() == ".pcm":
        return audio_path.read_bytes(), 16000
    raise ValueError(f"Unsupported audio type: {audio_path}")


async def _transcribe_pcm_chunk(
    adapter: GroqWhisperAdapter,
    pcm: bytes,
    *,
    seq: int,
) -> TranscriptSegment | None:
    if adapter._pcm_rms(pcm) < adapter.min_rms:  # noqa: SLF001
        return None
    wav_bytes = adapter._pcm_to_wav(pcm)  # noqa: SLF001
    from tempa.router.groq_router import get_router

    import asyncio

    router = get_router()
    model = router.route("stt")

    def _call() -> str:
        kwargs: dict[str, Any] = {
            "file": (f"chunk_{seq}.wav", wav_bytes),
            "model": model,
        }
        if adapter.language:
            kwargs["language"] = adapter.language
        result = router.client.audio.transcriptions.create(**kwargs)
        return getattr(result, "text", str(result)).strip()

    try:
        text = await asyncio.to_thread(_call)
    except Exception:
        logger.exception("Meeting audio chunk transcription failed")
        return None

    if not text or adapter._is_hallucination(text):  # noqa: SLF001
        return None

    return TranscriptSegment(
        text=text,
        seq=seq,
        ts_start=None,
        ts_end=None,
        speaker=None,
        is_final=True,
        confidence=None,
        lang=adapter.language,
        payload={},
    )


async def transcribe_pcm_to_segments(
    pcm: bytes,
    *,
    sample_rate: int = 16000,
    chunk_seconds: float = 30.0,
    language: str | None = "en",
    min_rms: float = 0.0,
) -> list[TranscriptSegment]:
    adapter = GroqWhisperAdapter(
        sample_rate=sample_rate,
        chunk_seconds=chunk_seconds,
        language=language,
        min_rms=min_rms,
    )
    bytes_per_chunk = int(sample_rate * 2 * chunk_seconds)
    segments: list[TranscriptSegment] = []
    seq = 0
    for offset in range(0, len(pcm), bytes_per_chunk):
        chunk = pcm[offset : offset + bytes_per_chunk]
        if len(chunk) < sample_rate * 2:  # skip tail shorter than ~1s of PCM16 mono
            continue
        seq += 1
        segment = await _transcribe_pcm_chunk(adapter, chunk, seq=seq)
        if segment:
            segments.append(segment)
    return segments


def _segment_to_jsonl_row(segment: TranscriptSegment) -> dict[str, Any]:
    return {
        "type": "segment",
        "seq": segment.seq,
        "ts_start": segment.ts_start,
        "ts_end": segment.ts_end,
        "speaker": segment.speaker,
        "diarized_speaker": segment.speaker,
        "is_final": segment.is_final,
        "confidence": segment.confidence,
        "lang": segment.lang,
        "text": segment.text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _extract_audio_from_video(meeting_id: str, meeting_dir: Path, safe_id: str) -> Path | None:
    """Fallback: pull audio track from system-captured MP4/WebM when PCM is silent."""
    import asyncio

    video_path = resolve_video_path(meeting_id)
    if not video_path or not video_path.exists():
        return None
    audio_dir = meeting_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_wav = audio_dir / f"{safe_id}_from_video.wav"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_wav),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not out_wav.exists():
        logger.warning(
            "Failed to extract audio from video for %s: %s",
            meeting_id,
            (stderr or b"").decode(errors="replace")[:200],
        )
        return None
    logger.info("Extracted transcription audio from video for %s → %s", meeting_id, out_wav)
    return out_wav


async def transcribe_meeting_audio(
    meeting_id: str,
    *,
    chunk_seconds: float = 30.0,
    force: bool = False,
) -> int:
    """Transcribe stored meeting audio into the transcript JSONL file."""
    settings = get_settings()
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = settings.meetings_dir / safe_id
    transcript_path = meeting_dir / "transcripts" / f"{safe_id}.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    _, existing = _parse_transcript_jsonl(transcript_path)
    if existing and not force:
        return len(existing)

    audio_path = resolve_audio_path(meeting_dir, safe_id)
    if not audio_path or not audio_path.exists():
        extracted = await _extract_audio_from_video(meeting_id, meeting_dir, safe_id)
        if extracted:
            audio_path = extracted
        else:
            raise FileNotFoundError(f"No audio for meeting {meeting_id}")

    pcm, sample_rate = _load_pcm_bytes(audio_path)
    if not pcm:
        raise ValueError(f"Empty audio for meeting {meeting_id}")

    peak_rms = pcm16_peak_rms(pcm)
    duration_s = len(pcm) / (sample_rate * 2)
    if is_silent_capture(peak_rms, duration_s):
        extracted = await _extract_audio_from_video(meeting_id, meeting_dir, safe_id)
        if extracted and extracted != audio_path:
            audio_path = extracted
            pcm, sample_rate = _load_pcm_bytes(audio_path)
            if not pcm:
                raise ValueError(f"Empty extracted audio for meeting {meeting_id}")

    segments: list[TranscriptSegment] = []
    max_whole_file_bytes = 24 * 1024 * 1024
    if audio_path.stat().st_size <= max_whole_file_bytes:
        import asyncio

        from tempa.router.groq_router import get_router

        try:
            text = await asyncio.to_thread(get_router().transcribe_file, audio_path)
        except Exception:
            logger.exception("Full-file transcription failed for %s", meeting_id)
            text = ""
        cleaned = text.strip()
        if cleaned:
            segments = [
                TranscriptSegment(
                    text=cleaned,
                    seq=1,
                    ts_start=None,
                    ts_end=None,
                    speaker=None,
                    is_final=True,
                    confidence=None,
                    lang="en",
                    payload={"source": "full_file"},
                )
            ]

    if not segments:
        segments = await transcribe_pcm_to_segments(
            pcm,
            sample_rate=sample_rate,
            chunk_seconds=chunk_seconds,
            min_rms=0.0,
        )
    if not segments:
        raise RuntimeError(f"Transcription produced no speech for meeting {meeting_id}")

    metadata: dict[str, Any] = {
        "type": "metadata",
        "meeting_id": meeting_id,
        "sample_rate": sample_rate,
        "stt_provider": "groq",
        "created_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "source": "post_process_audio",
    }
    if transcript_path.exists():
        first_line = transcript_path.read_text(encoding="utf-8").splitlines()[:1]
        if first_line:
            try:
                old_meta = json.loads(first_line[0])
                if old_meta.get("type") == "metadata":
                    metadata["original_created_at"] = old_meta.get("created_at")
            except json.JSONDecodeError:
                pass

    lines = [json.dumps(metadata, ensure_ascii=False)]
    lines.extend(json.dumps(_segment_to_jsonl_row(seg), ensure_ascii=False) for seg in segments)
    transcript_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Transcribed meeting %s: %s segments", meeting_id, len(segments))
    return len(segments)


async def summarize_meeting_from_transcript(
    meeting_id: str,
    *,
    send_notifications: bool = False,
) -> dict[str, Any]:
    """Regenerate minutes and archive from an existing transcript."""
    from tempa.meet.service import repair_meeting_finalize

    return await repair_meeting_finalize(
        meeting_id,
        send_notifications=send_notifications,
    )


async def process_meeting_from_audio(
    meeting_id: str,
    *,
    force_transcribe: bool = False,
    send_notifications: bool = False,
) -> dict[str, Any]:
    """Transcribe audio (if needed) then finalize minutes and archive."""
    from tempa.meet.service import repair_meeting_finalize

    segment_count = await transcribe_meeting_audio(meeting_id, force=force_transcribe)
    record = await repair_meeting_finalize(
        meeting_id,
        notify_number=None,
        send_notifications=send_notifications,
    )
    return {
        "meeting_id": meeting_id,
        "transcript_segments": segment_count,
        "minutes_status": record.get("minutes_status"),
        "title": record.get("title"),
    }


async def process_meetings_with_audio(*, send_notifications: bool = False) -> list[dict[str, Any]]:
    """Process all archived meetings that have audio but no transcript segments."""
    from tempa.meet.archive import list_meetings

    results: list[dict[str, Any]] = []
    for meeting in await list_meetings():
        artifacts = meeting.get("artifacts") or {}
        if not artifacts.get("audio"):
            continue
        path = meeting.get("transcript_path")
        _, segments = _parse_transcript_jsonl(Path(path)) if path else ("", [])
        if segments and meeting.get("minutes_status") == "complete":
            minutes = meeting.get("minutes") or {}
            if minutes.get("tldr") or minutes.get("summary"):
                continue
        try:
            results.append(
                await process_meeting_from_audio(
                    meeting["id"],
                    send_notifications=send_notifications,
                )
            )
        except Exception as exc:
            logger.exception("Failed to process meeting %s from audio", meeting["id"])
            results.append(
                {
                    "meeting_id": meeting["id"],
                    "error": str(exc),
                    "title": meeting.get("title"),
                }
            )
    return results
