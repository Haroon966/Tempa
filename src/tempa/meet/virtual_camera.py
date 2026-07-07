"""Tempa avatar file for Chromium --use-file-for-fake-video-capture (loops natively)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def default_mp4_path() -> Path:
    return get_settings().project_root / "config/assets/animated_tempa.mp4"


def default_mjpeg_path() -> Path:
    return get_settings().project_root / "config/assets/animated_tempa.mjpeg"


def prepare_virtual_camera_file(
    *,
    mp4: Path | None = None,
    dest: Path | None = None,
) -> Path | None:
    """Encode MP4 → MJPEG on disk. Chrome loops .mjpeg files indefinitely."""
    src = mp4 or default_mp4_path()
    out = dest or default_mjpeg_path()
    if not src.is_file():
        logger.warning("GMEET: virtual camera MP4 missing (%s)", src)
        return None
    if out.is_file() and out.stat().st_size > 1000:
        return out.resolve()
    if not shutil.which("ffmpeg"):
        logger.warning("GMEET: ffmpeg missing, cannot build virtual camera file")
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-an",
        "-vf",
        "scale=640:360",
        "-c:v",
        "mjpeg",
        "-q:v",
        "5",
        "-f",
        "mjpeg",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not out.is_file():
        logger.warning("GMEET: virtual camera encode failed: %s", (result.stderr or "")[:200])
        return None
    logger.info("GMEET: virtual camera file ready (%s, %d bytes)", out.name, out.stat().st_size)
    return out.resolve()
