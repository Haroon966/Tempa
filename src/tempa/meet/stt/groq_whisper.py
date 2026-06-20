from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import math
import re
import wave
from typing import Awaitable, Callable, Optional

from tempa.router.groq_router import get_router
from tempa.meet.stt.base import STTStreamingAdapter, TranscriptSegment

_logger = logging.getLogger(__name__)

OnSegment = Callable[[TranscriptSegment], Awaitable[None]]

_HALLUCINATION_RE = re.compile(
    r"^(thank you\.?|thanks\.?|\.+|you\.?|okay\.?|ok\.?|bye\.?|goodbye\.?)$",
    re.I,
)
_MIN_RMS = 80.0


class GroqWhisperAdapter(STTStreamingAdapter):
    """Buffer PCM audio and transcribe via Groq Whisper on chunk boundaries."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        chunk_seconds: float = 15.0,
        language: Optional[str] = None,
        min_rms: float = _MIN_RMS,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_seconds = chunk_seconds
        self.language = language
        self.min_rms = min_rms
        self._buffer = bytearray()
        self._seq = 0
        self._on_segment: Optional[OnSegment] = None
        self._task: Optional[asyncio.Task] = None
        self._closed = False
        self._bytes_per_chunk = int(sample_rate * 2 * chunk_seconds)

    async def connect(self) -> None:
        return None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        self._buffer.extend(pcm_bytes)

    async def start(self, on_segment) -> None:
        self._on_segment = on_segment
        self._task = asyncio.create_task(self._flush_loop())

    async def close(self) -> None:
        self._closed = True
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        if self._buffer:
            await self._transcribe_buffer(bytes(self._buffer), final=True)
            self._buffer.clear()

    async def _flush_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self.chunk_seconds)
            if len(self._buffer) >= self._bytes_per_chunk:
                chunk = bytes(self._buffer[: self._bytes_per_chunk])
                del self._buffer[: self._bytes_per_chunk]
                await self._transcribe_buffer(chunk, final=True)

    @staticmethod
    def _pcm_rms(pcm: bytes) -> float:
        if len(pcm) < 2:
            return 0.0
        count = len(pcm) // 2
        sum_squares = 0.0
        for i in range(0, count * 2, 2):
            sample = int.from_bytes(pcm[i : i + 2], "little", signed=True)
            sum_squares += sample * sample
        return math.sqrt(sum_squares / max(1, count))

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return True
        if _HALLUCINATION_RE.match(cleaned):
            return True
        if len(cleaned) <= 2 and cleaned in {".", "..", "..."}:
            return True
        return False

    def _pcm_to_wav(self, pcm: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    async def _transcribe_buffer(self, pcm: bytes, *, final: bool) -> None:
        if not pcm or not self._on_segment:
            return
        rms = self._pcm_rms(pcm)
        if rms < self.min_rms:
            _logger.debug("GMEET: skipping silent chunk rms=%.1f", rms)
            return

        wav_bytes = self._pcm_to_wav(pcm)
        router = get_router()
        model = router.route("stt")

        def _call() -> str:
            kwargs: dict = {
                "file": (f"chunk_{self._seq}.wav", wav_bytes),
                "model": model,
            }
            if self.language:
                kwargs["language"] = self.language
            result = router.client.audio.transcriptions.create(**kwargs)
            return getattr(result, "text", str(result)).strip()

        try:
            text = await asyncio.to_thread(_call)
        except Exception:
            _logger.exception("Groq Whisper transcription failed")
            return

        if not text or self._is_hallucination(text):
            _logger.debug("GMEET: dropped STT hallucination/silence text=%r rms=%.1f", text, rms)
            return

        self._seq += 1
        segment = TranscriptSegment(
            text=text,
            seq=self._seq,
            ts_start=None,
            ts_end=None,
            speaker=None,
            is_final=final,
            confidence=None,
            lang=self.language,
            payload={"rms": rms},
        )
        await self._on_segment(segment)
