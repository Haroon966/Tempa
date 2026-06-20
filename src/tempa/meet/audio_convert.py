from __future__ import annotations

import wave
from pathlib import Path


def pcm_to_wav(pcm_path: Path, wav_path: Path, *, sample_rate: int = 16000, channels: int = 1) -> Path:
    """FR-MEET-04: convert raw PCM16 capture to WAV."""
    pcm_bytes = pcm_path.read_bytes()
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return wav_path


def resolve_audio_path(meeting_dir: Path, meeting_id: str) -> Path | None:
    audio_dir = meeting_dir / "audio"
    if not audio_dir.exists():
        return None
    wav = audio_dir / f"{meeting_id}.wav"
    if wav.exists():
        return wav
    pcm_files = sorted(audio_dir.glob("*.pcm"))
    if not pcm_files:
        return None
    pcm_to_wav(pcm_files[0], wav)
    return wav
