import struct

from tempa.meet.audio_capture import (
    audio_capture_script,
    early_webrtc_hook_script,
    is_silent_capture,
    pcm16_peak_rms,
    pcm_file_peak_rms,
)


def test_early_hook_mentions_webrtc():
    script = early_webrtc_hook_script()
    assert "RTCPeerConnection" in script
    assert "__gmeetPendingStreams" in script


def test_capture_script_scans_video_elements():
    script = audio_capture_script(16000, 20, True)
    assert "audio, video" in script
    assert "__gmeetForceRescan" in script


def test_pcm16_peak_rms_detects_silence_vs_speech():
    silent = struct.pack("<" + "h" * 16000, *([0] * 16000))
    loud = struct.pack("<" + "h" * 16000, *([5000] * 16000))
    assert pcm16_peak_rms(silent) < 1
    assert pcm16_peak_rms(loud) > 1000


def test_is_silent_capture():
    assert is_silent_capture(2.0, 120.0) is True
    assert is_silent_capture(500.0, 120.0) is False
    assert is_silent_capture(2.0, 30.0) is False


def test_pcm_file_peak_rms(tmp_path):
    path = tmp_path / "test.pcm"
    path.write_bytes(struct.pack("<" + "h" * 8000, *([0] * 8000)))
    assert pcm_file_peak_rms(path) < 1
