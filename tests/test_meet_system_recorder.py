from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from unittest.mock import MagicMock

from tempa.meet.audio_capture import SILENT_CAPTURE_RMS_THRESHOLD, is_silent_capture
from tempa.meet.system_recorder import (
    SystemMeetingRecorder,
    resolve_pulse_monitor_source,
    system_capture_available,
    use_system_capture,
)


def test_system_capture_available_when_env_set(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("PULSE_SERVER", "unix:/tmp/pulse/native")
    assert system_capture_available() is True


def test_system_capture_unavailable_without_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("PULSE_SERVER", "unix:/tmp/pulse/native")
    assert system_capture_available() is False


def test_use_system_capture_respects_settings(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("PULSE_SERVER", "unix:/tmp/pulse/native")

    class _Settings:
        meet_system_capture_enabled = True

    monkeypatch.setattr("tempa.meet.system_recorder.get_settings", lambda: _Settings())
    monkeypatch.setattr("tempa.meet.system_recorder._pulse_ready", lambda: True)
    assert use_system_capture() is True


async def _test_recorder_pumps_pcm_to_callback(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("PULSE_SERVER", "unix:/tmp/pulse/native")

    class _Settings:
        meet_system_capture_enabled = True
        meet_pulse_monitor_source = "meet_sink.monitor"

    monkeypatch.setattr("tempa.meet.system_recorder.get_settings", lambda: _Settings())
    monkeypatch.setattr("tempa.meet.system_recorder._pulse_ready", lambda: True)

    loud_pcm = struct.pack("<" + "h" * 1600, *([3000] * 1600))
    chunks = [loud_pcm, b""]

    async def fake_create_subprocess_exec(*args, **kwargs):
        cmd = args[0] if args else ""
        proc = MagicMock()
        proc.pid = 42 if cmd == "ffmpeg" else 43
        proc.returncode = None
        if kwargs.get("stdout") == asyncio.subprocess.PIPE:
            proc.stdout = MagicMock()

            async def read(n):
                return chunks.pop(0) if chunks else b""

            proc.stdout.read = read
            proc.stderr = None
        else:
            proc.stdout = None
            proc.stderr = None

        async def wait():
            proc.returncode = 0

        proc.wait = wait

        async def send_signal(sig):
            proc.returncode = 0

        proc.send_signal = send_signal
        proc.kill = MagicMock()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    recorder = SystemMeetingRecorder("meet-1", tmp_path)
    received: list[bytes] = []

    async def on_chunk(data: bytes) -> None:
        received.append(data)

    recorder.on_pcm_chunk = on_chunk
    await recorder.start()
    await asyncio.sleep(0.05)
    result = await recorder.stop()

    assert recorder.pcm_path is not None
    assert recorder.pcm_path.exists()
    assert len(received) >= 1
    assert result["capture_source"] == "system"
    assert result["peak_rms"] > SILENT_CAPTURE_RMS_THRESHOLD


def test_recorder_pumps_pcm_to_callback(tmp_path, monkeypatch):
    asyncio.run(_test_recorder_pumps_pcm_to_callback(tmp_path, monkeypatch))


def test_resolve_pulse_monitor_source_env(monkeypatch):
    monkeypatch.setenv("MEET_PULSE_MONITOR_SOURCE", "meet_sink.monitor")
    assert resolve_pulse_monitor_source() == "meet_sink.monitor"


def test_resolve_pulse_monitor_source_settings(monkeypatch):
    monkeypatch.delenv("MEET_PULSE_MONITOR_SOURCE", raising=False)

    class _Settings:
        meet_pulse_monitor_source = "meet_sink.monitor"

    monkeypatch.setattr("tempa.meet.system_recorder.get_settings", lambda: _Settings())
    assert resolve_pulse_monitor_source() == "meet_sink.monitor"
    assert is_silent_capture(2.0, 120.0) is True
    assert is_silent_capture(500.0, 120.0) is False


def test_resolve_video_path_prefers_mp4(tmp_path, monkeypatch):
    from tempa.meet.media import resolve_video_path

    meeting_id = "abc"
    video_dir = tmp_path / meeting_id / "video"
    video_dir.mkdir(parents=True)
    (video_dir / f"{meeting_id}.webm").write_bytes(b"webm")
    mp4 = video_dir / f"{meeting_id}.mp4"
    mp4.write_bytes(b"mp4")

    class _Settings:
        meetings_dir = tmp_path

    monkeypatch.setattr("tempa.meet.media.get_settings", lambda: _Settings())
    assert resolve_video_path(meeting_id) == mp4
