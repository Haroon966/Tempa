"""YouTube + screen-share helpers for A/V capture testing in the meet worker."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)

SCREEN_CAPTURE_LAUNCH_ARG = "--auto-select-desktop-capture-source=Entire screen"


@dataclass
class AvTestPlayer:
    process: subprocess.Popen[bytes] | None
    media_path: Path


def _ensure_yt_dlp() -> str:
    path = shutil.which("yt-dlp")
    if not path:
        raise RuntimeError("yt-dlp not installed (required for AV test mode)")
    return path


def download_youtube_clip(url: str, dest_dir: Path, *, duration_seconds: int = 60) -> Path:
    """Download the first *duration_seconds* of a YouTube video as mp4."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "av_test_clip.mp4"
    if out.exists() and out.stat().st_size > 50_000:
        return out

    yt_dlp = _ensure_yt_dlp()
    section = f"*0-{max(1, duration_seconds)}"
    cmd = [
        yt_dlp,
        "-f",
        "best[height<=720][ext=mp4]/best[height<=720]/best",
        "--download-sections",
        section,
        "--force-overwrites",
        "-o",
        str(out),
        url,
    ]
    _logger.info("GMEET AV-TEST: downloading clip (%ss) from %s", duration_seconds, url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(
            f"yt-dlp failed ({result.returncode}): {(result.stderr or result.stdout or '')[:400]}"
        )
    return out


def start_youtube_player(media_path: Path, *, duration_seconds: int = 60) -> AvTestPlayer:
    """Play video fullscreen on DISPLAY; audio routes to the default Pulse sink."""
    display = os.environ.get("DISPLAY", ":99")
    if not shutil.which("ffplay"):
        raise RuntimeError("ffplay not found")

    cmd = [
        "ffplay",
        "-autoexit",
        "-t",
        str(max(1, duration_seconds)),
        "-fs",
        "-noborder",
        "-loglevel",
        "error",
        str(media_path),
    ]
    _logger.info("GMEET AV-TEST: starting ffplay on %s for %ss", display, duration_seconds)
    proc = subprocess.Popen(cmd, env={**os.environ, "DISPLAY": display})
    return AvTestPlayer(process=proc, media_path=media_path)


def stop_youtube_player(player: AvTestPlayer | None) -> None:
    if not player or not player.process:
        return
    proc = player.process
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def start_screen_share(page) -> bool:
    """Click Present now and share the entire screen (Chrome auto-selects with fake UI)."""
    present_selectors = [
        'button[aria-label*="Present now" i]',
        'button[aria-label*="Share screen" i]',
        'button[aria-label*="Present" i]',
        'button[data-tooltip*="Present" i]',
    ]
    clicked = False
    for selector in present_selectors:
        btn = page.locator(selector).first
        if await btn.count() > 0:
            try:
                await btn.wait_for(state="visible", timeout=8000)
                await btn.click()
                clicked = True
                _logger.info("GMEET AV-TEST: clicked present (%s)", selector)
                break
            except Exception:
                continue
    if not clicked:
        _logger.warning("GMEET AV-TEST: present button not found")
        return False

    await asyncio.sleep(1.5)

    for label in ("Entire screen", "Your entire screen", "Full screen", "Screen"):
        option = page.locator(f"text=/{label}/i").first
        if await option.count() > 0:
            try:
                if await option.is_visible():
                    await option.click()
                    _logger.info("GMEET AV-TEST: selected %s", label)
                    break
            except Exception:
                continue

    await asyncio.sleep(0.5)
    share = page.locator('button:has-text("Share"), button:has-text("Start sharing")').first
    if await share.count() > 0:
        try:
            if await share.is_visible():
                await share.click()
                _logger.info("GMEET AV-TEST: confirmed screen share")
        except Exception:
            _logger.debug("GMEET AV-TEST: share confirm click skipped", exc_info=True)

    await asyncio.sleep(2)
    stop_presenting = page.locator('button[aria-label*="Stop presenting" i], button[aria-label*="Stop sharing" i]')
    if await stop_presenting.count() > 0:
        _logger.info("GMEET AV-TEST: screen share active")
        return True
    _logger.warning("GMEET AV-TEST: could not confirm screen share started")
    return False


async def run_av_test(
    page,
    youtube_url: str,
    work_dir: Path,
    *,
    duration_seconds: int = 60,
) -> AvTestPlayer | None:
    """Download YouTube clip, play on Xvfb, and start Meet screen share."""
    clip = await asyncio.to_thread(download_youtube_clip, youtube_url, work_dir, duration_seconds=duration_seconds)
    player = await asyncio.to_thread(start_youtube_player, clip, duration_seconds=duration_seconds)
    await asyncio.sleep(2)
    shared = await start_screen_share(page)
    if not shared:
        _logger.warning("GMEET AV-TEST: continuing without confirmed screen share")
    return player
