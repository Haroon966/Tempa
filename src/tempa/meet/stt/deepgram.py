from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Optional

import websockets

from tempa.meet.stt.base import STTStreamingAdapter, TranscriptSegment

_logger = logging.getLogger(__name__)


class DeepgramStreamingAdapter(STTStreamingAdapter):
    """Stream PCM to Deepgram for live transcription with diarization."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        language: str = "en",
        open_timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self.sample_rate = sample_rate
        self.channels = channels
        self.language = language
        self.open_timeout = open_timeout
        self._ws = None
        self._recv_task: Optional[asyncio.Task] = None
        self._seq = 0

    def _build_ws_url(self) -> str:
        return (
            "wss://api.deepgram.com/v1/listen"
            f"?encoding=linear16&sample_rate={self.sample_rate}&channels={self.channels}"
            f"&punctuate=true&interim_results=true&diarize=true&model=nova-3"
            f"&language={self.language}"
        )

    async def connect(self) -> None:
        api_key = (self._api_key or "").strip()
        if not api_key:
            raise RuntimeError("Deepgram api_key is required for Deepgram streaming.")
        self._ws = await websockets.connect(
            self._build_ws_url(),
            additional_headers={"Authorization": f"Token {api_key}"},
            max_size=None,
            open_timeout=self.open_timeout,
        )
        _logger.info("GMEET: Deepgram websocket connected")

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or not self._ws:
            return
        await self._ws.send(pcm_bytes)

    async def start(self, on_segment: Callable[[TranscriptSegment], Awaitable[None]]) -> None:
        if not self._ws:
            return
        self._recv_task = asyncio.create_task(self._recv_loop(on_segment))

    async def _recv_loop(self, on_segment: Callable[[TranscriptSegment], Awaitable[None]]) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                if not message:
                    continue
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    continue
                segment = self._parse_message(payload)
                if segment:
                    await on_segment(segment)
        except Exception:
            _logger.exception("GMEET: Deepgram recv loop failed")

    def _parse_message(self, payload: dict) -> Optional[TranscriptSegment]:
        if payload.get("type") != "Results":
            return None
        channel = payload.get("channel") or {}
        alternatives = channel.get("alternatives") or []
        if not alternatives:
            return None
        alt = alternatives[0] or {}
        transcript = (alt.get("transcript") or "").strip()
        if not transcript:
            return None

        words = alt.get("words") or []
        speaker = None
        ts_start = None
        ts_end = None
        if words:
            first = words[0] or {}
            last = words[-1] or {}
            speaker = first.get("speaker")
            ts_start = first.get("start")
            ts_end = last.get("end")

        self._seq += 1
        speaker_label = f"Speaker {speaker}" if speaker is not None else None
        return TranscriptSegment(
            text=transcript,
            seq=self._seq,
            ts_start=ts_start,
            ts_end=ts_end,
            speaker=speaker_label,
            is_final=bool(payload.get("is_final")),
            confidence=alt.get("confidence"),
            lang=self.language,
            payload=payload,
        )

    async def close(self) -> None:
        if self._ws:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                _logger.exception("GMEET: Deepgram websocket close failed")
        self._ws = None
