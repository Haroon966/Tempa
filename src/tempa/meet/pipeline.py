"""Pipeline orchestrator that wires adapters to a raw MeetSession."""

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from tempa.meet.audio_capture import audio_capture_script
from tempa.meet.audio_writer import AudioDumpWriter
from tempa.meet.config import AudioConfig, SttConfig
from tempa.meet.manifest_writer import ManifestWriter
from tempa.meet.joiner import MeetSession
from tempa.meet.participants import ParticipantScraper
from tempa.meet.speakers import SpeakerAttributionAdapter, create_speaker_attribution
from tempa.meet.speaker_event_writer import SpeakerEventWriter
from tempa.meet.storage import ArtifactStorageAdapter, LocalStorageAdapter
from tempa.meet.stt.base import STTStreamingAdapter
from tempa.meet.stt.factory import create_stt_adapter
from tempa.meet.transcript_writer import TranscriptWriter

_logger = logging.getLogger(__name__)


async def _connect_stt_with_retries(
    stt_adapter: STTStreamingAdapter,
    *,
    provider: str,
    retries: int,
    initial_delay_s: float,
    max_delay_s: float,
) -> None:
    for attempt in range(1, retries + 1):
        try:
            await stt_adapter.connect()
            return
        except Exception as err:
            if attempt >= retries:
                raise
            delay_s = min(max_delay_s, initial_delay_s * (2 ** (attempt - 1)))
            _logger.warning(
                "GMEET: STT connect failed provider=%s attempt=%s/%s retry_in=%.2fs err=%s",
                provider,
                attempt,
                retries,
                delay_s,
                err,
            )
            await asyncio.sleep(delay_s)


@dataclass
class PipelineSession:
    page: Optional[object] = None
    audio_writer: Optional[AudioDumpWriter] = None
    stt_adapter: Optional[STTStreamingAdapter] = None
    speaker_attribution: Optional[SpeakerAttributionAdapter] = None
    transcript_writer: Optional[TranscriptWriter] = None
    speaker_event_writer: Optional[SpeakerEventWriter] = None
    participant_scraper: Optional[ParticipantScraper] = None
    manifest_writer: Optional[ManifestWriter] = None

    async def close(self) -> dict:
        close_result = {"audio": None, "transcript": None, "speaker_events": None, "manifest": None}
        if self.page:
            try:
                await self.page.evaluate(
                    "(async () => { if (window.__gmeetStopAudioCapture) await window.__gmeetStopAudioCapture(); })()"
                )
            except Exception as err:
                _logger.debug("GMEET: audio capture teardown skipped err=%s", err)
        if self.speaker_attribution:
            self.speaker_attribution.stop()
        if self.stt_adapter:
            await self.stt_adapter.close()
        if self.audio_writer:
            result = self.audio_writer.close()
            close_result["audio"] = result
            _logger.info(
                "GMEET: audio dump closed local=%s remote=%s bytes=%s duration=%.2fs",
                result.get("local_path"),
                result.get("remote_path"),
                result.get("bytes_written"),
                result.get("duration_seconds", 0),
            )
        if self.transcript_writer:
            close_result["transcript"] = self.transcript_writer.close()
        if self.speaker_event_writer:
            close_result["speaker_events"] = self.speaker_event_writer.close()
        if self.participant_scraper:
            self.participant_scraper.stop()
        if self.manifest_writer:
            if self.participant_scraper:
                for pid, info in self.participant_scraper.get_participants().items():
                    self.manifest_writer.add_participant(
                        pid,
                        display_name=info.display_name,
                        email=info.email,
                        avatar_url=info.avatar_url,
                        first_seen_at=info.first_seen_at,
                    )
            close_result["manifest"] = self.manifest_writer.close()
        return close_result


async def setup_pipeline(
    session: MeetSession,
    *,
    meeting_id: str,
    audio: AudioConfig = None,
    stt: SttConfig = None,
    output_dir: str = "./generated",
    storage_adapter: Optional[ArtifactStorageAdapter] = None,
    stt_adapter: Optional[STTStreamingAdapter] = None,
    use_browser_audio: bool = True,
) -> PipelineSession:
    if audio is None:
        audio = AudioConfig()
    if stt is None:
        stt = SttConfig()
    if storage_adapter is None:
        storage_adapter = LocalStorageAdapter()

    safe_meeting_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_base_dir = os.path.join(output_dir, safe_meeting_id)

    page = session.page
    audio_writer = None
    speaker_attribution = None
    transcript_writer = None

    if audio.dump_enabled and use_browser_audio:
        try:
            audio_writer = AudioDumpWriter(
                meeting_id=meeting_id,
                sample_rate=audio.sample_rate,
                channels=1,
                audio_dir=os.path.join(meeting_base_dir, "audio"),
                storage_adapter=storage_adapter,
            )
            audio_writer.open()
            _logger.info("GMEET: audio dump writer initialized")
        except Exception:
            _logger.exception("GMEET: failed to initialize audio dump writer")
            audio_writer = None

    # --- Speaker events (DOM-based active speaker detection) ---
    speaker_event_writer = None

    if stt.diarization and stt.diarization != "stt_native":
        try:
            speaker_event_writer = SpeakerEventWriter(
                meeting_id=meeting_id,
                speaker_events_dir=os.path.join(meeting_base_dir, "speaker_events"),
                storage_adapter=storage_adapter,
            )
            speaker_event_writer.open()
        except Exception:
            _logger.exception("GMEET: failed to start speaker event writer")
            speaker_event_writer = None

        def on_speaker_change(speaker_name, is_speaking):
            if speaker_event_writer:
                speaker_event_writer.write_event(speaker_name, time.time(), is_speaking)

        try:
            speaker_attribution = create_speaker_attribution(stt.diarization, page=page)
            await speaker_attribution.start(on_speaker_change=on_speaker_change)
        except Exception:
            _logger.exception("GMEET: failed to start speaker attribution (%s)", stt.diarization)
            speaker_attribution = None

    # --- Participant scraper + manifest (always enabled) ---
    participant_scraper = None
    manifest_writer = None

    try:
        participant_scraper = ParticipantScraper(page=page)
        await participant_scraper.start()
    except Exception:
        _logger.exception("GMEET: failed to start participant scraper")
        participant_scraper = None

    try:
        manifest_writer = ManifestWriter(
            meeting_id=meeting_id,
            manifests_dir=os.path.join(meeting_base_dir, "manifests"),
            storage_adapter=storage_adapter,
        )
        manifest_writer.open()
    except Exception:
        _logger.exception("GMEET: failed to start manifest writer")
        manifest_writer = None

    # --- STT (optional) ---
    if stt_adapter or stt.provider:
        try:
            transcript_writer = TranscriptWriter(
                meeting_id=meeting_id,
                sample_rate=audio.sample_rate,
                stt_provider=stt.provider,
                transcript_dir=os.path.join(meeting_base_dir, "transcripts"),
                storage_adapter=storage_adapter,
            )
            transcript_writer.open()
        except Exception:
            _logger.exception("GMEET: failed to start transcript writer")
            transcript_writer = None

        try:
            if stt_adapter is None:
                adapter_kwargs = dict(stt.extra)
                adapter_kwargs.setdefault("sample_rate", audio.sample_rate)
                if stt.api_key:
                    adapter_kwargs.setdefault("api_key", stt.api_key)
                stt_adapter = create_stt_adapter(stt.provider, **adapter_kwargs)
            await _connect_stt_with_retries(
                stt_adapter,
                provider=stt.provider,
                retries=max(1, stt.connect_retries),
                initial_delay_s=max(0.1, stt.connect_initial_delay_s),
                max_delay_s=max(0.1, stt.connect_max_delay_s),
            )

            async def on_segment(segment):
                speaker_name = speaker_attribution.get_speaker_for_segment(segment) if speaker_attribution else None
                _logger.info(
                    "GMEET: stt segment seq=%s final=%s speaker=%s diarized=%s text=%s",
                    segment.seq,
                    segment.is_final,
                    speaker_name,
                    segment.speaker,
                    segment.text,
                )
                if transcript_writer:
                    transcript_writer.write_segment(segment, speaker_name=speaker_name)

            await stt_adapter.start(on_segment)
        except Exception:
            _logger.exception("GMEET: failed to start STT (%s)", stt.provider)
            stt_adapter = None

    # --- Browser audio capture JS (skipped when system PulseAudio capture is active) ---
    if use_browser_audio and (audio_writer or stt_adapter or speaker_attribution):
        try:

            async def handle_audio_chunk(source, payload):
                if not payload:
                    return
                if isinstance(payload, dict) and "pcm16_b64" in payload:
                    try:
                        decoded = base64.b64decode(payload["pcm16_b64"])
                    except Exception:
                        _logger.exception("GMEET: failed to decode audio chunk")
                        return
                    if audio_writer:
                        audio_writer.write_chunk(decoded)
                    if stt_adapter:
                        await stt_adapter.send_audio(decoded)

            async def handle_audio_debug(source, payload):
                if not payload:
                    return
                if isinstance(payload, dict):
                    _logger.info("GMEET: audio debug %s", payload)

            await page.expose_binding("onAudioChunk", handle_audio_chunk)
            if audio.debug:
                await page.expose_binding("onAudioDebug", handle_audio_debug)
            await page.evaluate(audio_capture_script(audio.sample_rate, audio.chunk_ms, audio.debug))
            _logger.info("GMEET: audio capture initialized")
        except Exception:
            _logger.exception("GMEET: failed to start audio capture")

    return PipelineSession(
        page=page,
        audio_writer=audio_writer,
        stt_adapter=stt_adapter,
        speaker_attribution=speaker_attribution,
        transcript_writer=transcript_writer,
        speaker_event_writer=speaker_event_writer,
        participant_scraper=participant_scraper,
        manifest_writer=manifest_writer,
    )
