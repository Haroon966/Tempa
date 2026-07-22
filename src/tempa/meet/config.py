"""Typed configuration models for the GMeet worker."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    chunk_ms: int = 20
    debug: bool = True
    dump_enabled: bool = True


@dataclass
class VideoConfig:
    record_enabled: bool = True
    width: int = 1280
    height: int = 720


@dataclass
class SttConfig:
    provider: Optional[str] = None
    api_key: Optional[str] = None
    diarization: str = "correlation"
    extra: dict = field(default_factory=lambda: {"chunk_seconds": 15.0, "language": "en"})
    connect_retries: int = 4
    connect_initial_delay_s: float = 2.0
    connect_max_delay_s: float = 15.0


@dataclass
class JoinConfig:
    headless: bool = True
    storage_state_path: Optional[str] = None
    bot_name: str = "Meeto"
    disable_mic: bool = True
    disable_camera: bool = True
    virtual_camera_path: Optional[str] = None
    join_timeout_ms: int = 90000
    screenshot_dir: Optional[str] = None
    display: Optional[str] = None
    pulse_sink: Optional[str] = None


@dataclass
class WorkerConfig:
    meeting_id: str
    meet_url: str
    duration_seconds: int = 3600
    output_dir: str = "./generated"
    audio: AudioConfig = field(default_factory=AudioConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    join: JoinConfig = field(default_factory=JoinConfig)
    calendar_event_id: str | None = None
    calendar_event_start: str | None = None
    calendar_event_end: str | None = None
    attendee_emails: list[str] = field(default_factory=list)
    organizer_email: str | None = None
    started_at: str | None = None
    av_test_youtube_url: str | None = None
    pulse_monitor_source: str | None = None
