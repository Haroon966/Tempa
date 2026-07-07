"""Tests for virtual camera settings resolution."""

from pathlib import Path

from tempa.settings import Settings


def test_resolved_virtual_camera_static_mjpeg(tmp_path):
    mjpeg = tmp_path / "animated_tempa.mjpeg"
    mjpeg.write_bytes(b"JFIF")

    settings = Settings(
        meet_virtual_camera_enabled=True,
        meet_virtual_camera_path=mjpeg,
    )
    assert settings.resolved_virtual_camera_path() == mjpeg.resolve()


def test_resolved_virtual_camera_static_y4m(tmp_path):
    y4m = tmp_path / "animated_tempa.y4m"
    y4m.write_bytes(b"YUV4MPEG2")

    settings = Settings(
        meet_virtual_camera_enabled=True,
        meet_virtual_camera_path=y4m,
    )
    assert settings.resolved_virtual_camera_path() == y4m


def test_resolved_virtual_camera_path(tmp_path):
    y4m = tmp_path / "animated_tempa.y4m"
    y4m.write_bytes(b"y4m")

    settings = Settings(
        meet_virtual_camera_enabled=True,
        meet_virtual_camera_path=y4m,
    )
    assert settings.resolved_virtual_camera_path() == y4m


def test_resolved_virtual_camera_missing_file():
    settings = Settings(
        meet_virtual_camera_enabled=True,
        meet_virtual_camera_path=Path("/nonexistent/animated_tempa.y4m"),
    )
    assert settings.resolved_virtual_camera_path() is None


def test_resolved_virtual_camera_disabled():
    settings = Settings(meet_virtual_camera_enabled=False)
    assert settings.resolved_virtual_camera_path() is None


def test_resolved_silent_fake_audio_path():
    settings = Settings()
    path = settings.resolved_silent_fake_audio_path()
    assert path is not None
    assert path.name == "silent_48k.wav"
    assert path.is_file()
