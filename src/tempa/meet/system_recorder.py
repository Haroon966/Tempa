"""OS-level meeting capture via FFmpeg + PulseAudio (meet-worker)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from tempa.meet.audio_capture import SILENT_CAPTURE_RMS_THRESHOLD, pcm16_peak_rms
from tempa.settings import get_settings

_logger = logging.getLogger(__name__)

# 20 ms of PCM16 mono @ 16 kHz
_PCM_CHUNK_BYTES = 16000 * 2 * 20 // 1000


def system_capture_available() -> bool:
    """True when Pulse + DISPLAY are configured (meet-worker container)."""
    display = os.environ.get("DISPLAY", "").strip()
    pulse = os.environ.get("PULSE_SERVER", "").strip() or os.environ.get("XDG_RUNTIME_DIR", "").strip()
    return bool(display and pulse)


def use_system_capture() -> bool:
    settings = get_settings()
    return bool(settings.meet_system_capture_enabled and system_capture_available())


def resolve_pulse_monitor_source() -> str:
    """Pulse monitor device for capturing Chrome/Meet playback."""
    env = os.environ.get("MEET_PULSE_MONITOR_SOURCE", "").strip()
    if env:
        return env
    return get_settings().meet_pulse_monitor_source


def _pulse_ready() -> bool:
    pulse_server = os.environ.get("PULSE_SERVER", "").strip()
    if not pulse_server:
        return False
    try:
        result = subprocess.run(
            ["pactl", "info"],
            capture_output=True,
            timeout=3,
            check=False,
            env={**os.environ, "PULSE_SERVER": pulse_server},
        )
        return result.returncode == 0
    except Exception:
        return False


def _ensure_pulse_running() -> None:
    if _pulse_ready():
        return
    script = Path(__file__).resolve().parents[3] / "scripts" / "meet-worker-entrypoint.sh"
    _logger.warning("GMEET: PulseAudio not reachable; attempting restart")
    with contextlib.suppress(Exception):
        subprocess.run(
            [
                "sh",
                "-c",
                (
                    'export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/pulse-runtime}"; '
                    'export PULSE_SERVER="${PULSE_SERVER:-unix:${XDG_RUNTIME_DIR}/pulse/native}"; '
                    "pulseaudio --daemonize --exit-idle-time=-1 --disallow-exit 2>/dev/null || true; "
                    "sleep 1; "
                    "pactl load-module module-null-sink sink_name=meet_sink_0 "
                    "sink_properties=device.description=MeetCapture0 2>/dev/null || true; "
                    "pactl set-default-sink meet_sink_0 2>/dev/null || true; "
                    "pactl set-default-source meet_sink_0.monitor 2>/dev/null || true"
                ),
            ],
            timeout=10,
            check=False,
            env=os.environ.copy(),
        )
    if not _pulse_ready():
        _logger.error("GMEET: PulseAudio still unavailable after restart attempt")


@dataclass
class SystemRecorderStats:
    bytes_written: int = 0
    peak_rms: float = 0.0
    chunks_pumped: int = 0


@dataclass
class SystemMeetingRecorder:
    """Record X11 display + PulseAudio monitor; pump PCM for STT."""

    meeting_id: str
    meeting_dir: Path
    width: int = 1280
    height: int = 720
    fps: int = 30
    sample_rate: int = 16000
    display: str = ":99"
    pulse_source: str = ""
    on_pcm_chunk: Optional[Callable[[bytes], Awaitable[None]]] = None
    _video_proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    _pcm_proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    _pump_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _monitor_task: Optional[asyncio.Task] = field(default=None, repr=False)
    stats: SystemRecorderStats = field(default_factory=SystemRecorderStats)
    video_path: Optional[Path] = field(default=None, repr=False)
    pcm_path: Optional[Path] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.meeting_dir = Path(self.meeting_dir)
        if not self.pulse_source:
            self.pulse_source = resolve_pulse_monitor_source()
        safe_id = self.meeting_id.replace("/", "_").replace("\\", "_")
        video_dir = self.meeting_dir / "video"
        audio_dir = self.meeting_dir / "audio"
        video_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)
        self.video_path = video_dir / f"{safe_id}.mp4"
        self.pcm_path = audio_dir / f"{safe_id}.pcm"

    async def start(self) -> None:
        if not use_system_capture():
            raise RuntimeError("System capture is not enabled or not available in this environment")

        _ensure_pulse_running()

        display_input = self.display if self.display.startswith(":") else f":{self.display}"
        video_size = f"{self.width}x{self.height}"
        pulse_ok = _pulse_ready()

        if pulse_ok:
            # Single MP4 with embedded AAC — permanent A/V in one file.
            video_cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-thread_queue_size",
                "512",
                "-f",
                "x11grab",
                "-video_size",
                video_size,
                "-framerate",
                str(self.fps),
                "-i",
                display_input,
                "-thread_queue_size",
                "512",
                "-f",
                "pulse",
                "-i",
                self.pulse_source,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(self.fps * 2),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+frag_keyframe+empty_moov+default_base_moof",
                str(self.video_path),
            ]
        else:
            _logger.warning(
                "GMEET: starting video-only system capture meeting=%s (no PulseAudio)",
                self.meeting_id,
            )
            video_cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "x11grab",
                "-video_size",
                video_size,
                "-framerate",
                str(self.fps),
                "-i",
                display_input,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(self.fps * 2),
                "-movflags",
                "+frag_keyframe+empty_moov+default_base_moof",
                str(self.video_path),
            ]

        pcm_cmd = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "pulse",
            "-i",
            self.pulse_source,
            "-f",
            "s16le",
            "-ar",
            str(self.sample_rate),
            "-ac",
            "1",
            "pipe:1",
        ]

        self._video_proc = await asyncio.create_subprocess_exec(*video_cmd)
        self._pcm_proc = None
        if pulse_ok:
            self._pcm_proc = await asyncio.create_subprocess_exec(
                *pcm_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._pump_task = asyncio.create_task(self._pump_pcm_loop())
            self._monitor_task = asyncio.create_task(self._monitor_health())

        _logger.info(
            "GMEET: system recorder started meeting=%s video=%s pcm=%s pulse=%s av_embedded=%s video_pid=%s pcm_pid=%s",
            self.meeting_id,
            self.video_path,
            self.pcm_path,
            self.pulse_source,
            pulse_ok,
            self._video_proc.pid,
            self._pcm_proc.pid if self._pcm_proc else None,
        )

    async def _pump_pcm_loop(self) -> None:
        assert self._pcm_proc and self._pcm_proc.stdout and self.pcm_path
        pcm_file = self.pcm_path.open("wb")
        try:
            while True:
                chunk = await self._pcm_proc.stdout.read(_PCM_CHUNK_BYTES)
                if not chunk:
                    break
                pcm_file.write(chunk)
                self.stats.bytes_written += len(chunk)
                self.stats.chunks_pumped += 1
                if len(chunk) >= 2:
                    samples = struct.unpack("<" + "h" * (len(chunk) // 2), chunk)
                    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
                    self.stats.peak_rms = max(self.stats.peak_rms, rms)
                if self.on_pcm_chunk:
                    await self.on_pcm_chunk(chunk)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("GMEET: system PCM pump failed meeting=%s", self.meeting_id)
        finally:
            pcm_file.close()

    async def _monitor_health(self) -> None:
        for attempt in range(10):
            await asyncio.sleep(30)
            if self.stats.peak_rms >= SILENT_CAPTURE_RMS_THRESHOLD:
                _logger.info(
                    "GMEET: system audio healthy meeting=%s peak_rms=%.1f bytes=%s",
                    self.meeting_id,
                    self.stats.peak_rms,
                    self.stats.bytes_written,
                )
                return
            _logger.warning(
                "GMEET: low system audio meeting=%s attempt=%s peak_rms=%.1f bytes=%s",
                self.meeting_id,
                attempt + 1,
                self.stats.peak_rms,
                self.stats.bytes_written,
            )

    async def stop(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "capture_source": "system",
            "video_path": str(self.video_path) if self.video_path else None,
            "pcm_path": str(self.pcm_path) if self.pcm_path else None,
            "bytes_written": self.stats.bytes_written,
            "peak_rms": round(self.stats.peak_rms, 2),
            "silent_capture": False,
            "pulse_source": self.pulse_source,
        }

        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task

        if self._pcm_proc and self._pcm_proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._pcm_proc.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._pcm_proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._pcm_proc.kill()
                await self._pcm_proc.wait()

        if self._pump_task:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(self._pump_task, timeout=5.0)

        if self._video_proc and self._video_proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._video_proc.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._video_proc.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                self._video_proc.kill()
                await self._video_proc.wait()

        if self.pcm_path and self.pcm_path.exists() and self.pcm_path.stat().st_size > 0:
            result["peak_rms"] = round(pcm16_peak_rms(self.pcm_path.read_bytes()), 2)
            result["bytes_written"] = self.pcm_path.stat().st_size
            duration = result["bytes_written"] / (self.sample_rate * 2)
            result["duration_seconds"] = round(duration, 2)
            result["silent_capture"] = duration >= 60 and result["peak_rms"] < SILENT_CAPTURE_RMS_THRESHOLD
            if result["silent_capture"]:
                _logger.warning(
                    "GMEET: silent system capture meeting=%s peak_rms=%.1f",
                    self.meeting_id,
                    result["peak_rms"],
                )

        if self.video_path and self.video_path.exists() and self.video_path.stat().st_size > 0:
            from tempa.meet.media import finalize_meeting_media_files

            media_result = await asyncio.to_thread(finalize_meeting_media_files, self.meeting_id)
            result.update(media_result)
            if self.video_path.exists():
                result["video_size_bytes"] = self.video_path.stat().st_size
        else:
            _logger.warning("GMEET: system video missing meeting=%s path=%s", self.meeting_id, self.video_path)

        _logger.info("GMEET: system recorder stopped meeting=%s result=%s", self.meeting_id, result)
        return result
