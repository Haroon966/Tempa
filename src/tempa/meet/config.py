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
    join_timeout_ms: int = 90000
    screenshot_dir: Optional[str] = None


@dataclass
class WorkerConfig:
    meeting_id: str
    meet_url: str
    duration_seconds: int = 3600
    output_dir: str = "./generated"
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    join: JoinConfig = field(default_factory=JoinConfig)
    calendar_event_id: str | None = None
    calendar_event_start: str | None = None
    calendar_event_end: str | None = None
    attendee_emails: list[str] = field(default_factory=list)
    started_at: str | None = None
