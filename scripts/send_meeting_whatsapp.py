#!/usr/bin/env python3
"""Send meeting video + audio to the owner WhatsApp number."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from tempa.channels.whatsapp.outbound import send_whatsapp_media, send_whatsapp_message
from tempa.channels.whatsapp.reply import load_default_whatsapp_number
from tempa.meet.media import finalize_mp4_for_playback, resolve_playable_video_path
from tempa.settings import get_settings


def _prepare_media(meeting_id: str) -> tuple[Path, Path, str]:
    settings = get_settings()
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = settings.meetings_dir / safe_id

    title = meeting_id
    meta = meeting_dir / "manifest.json"
    if meta.exists():
        import json

        try:
            title = json.loads(meta.read_text(encoding="utf-8")).get("title") or title
        except Exception:
            pass

    video_src = resolve_playable_video_path(meeting_id)
    if not video_src:
        raise SystemExit(f"No video for meeting {meeting_id}")
    finalize_mp4_for_playback(video_src)

    wa_video = meeting_dir / "video" / f"{safe_id}_wa.mp4"
    if not wa_video.exists() or wa_video.stat().st_size < 1000:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video_src),
                "-vf",
                "scale=854:480",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                str(wa_video),
            ],
            check=True,
        )

    audio_ogg = meeting_dir / "audio" / f"{safe_id}.ogg"
    audio_wav = meeting_dir / "audio" / f"{safe_id}.wav"
    if not audio_ogg.exists():
        if not audio_wav.exists():
            raise SystemExit(f"No audio for meeting {meeting_id}")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(audio_wav),
                "-c:a",
                "libopus",
                "-b:a",
                "64k",
                str(audio_ogg),
            ],
            check=True,
        )

    return wa_video, audio_ogg, title


async def _send(meeting_id: str, *, number: str | None = None) -> None:
    wa_video, audio_ogg, title = _prepare_media(meeting_id)
    target = number or load_default_whatsapp_number()
    if not target:
        raise SystemExit("No WhatsApp number configured")

    intro = await send_whatsapp_message(
        target,
        f"Meeting media: {title}",
        skip_safety=True,
        require_user_confirmation=False,
    )
    if intro.get("status") == "paused":
        raise SystemExit(intro.get("reason", "WhatsApp disconnected"))

    for path, caption in (
        (wa_video, f"Video: {title}"),
        (audio_ogg, f"Audio: {title}"),
    ):
        result = await send_whatsapp_media(
            target,
            str(path),
            caption=caption,
            mediatype="document",
            require_user_confirmation=False,
        )
        if result.get("status") == "paused":
            raise SystemExit(result.get("reason", "WhatsApp disconnected"))
        print(f"sent {path.name}: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting_id", help="Meeting UUID")
    parser.add_argument("--number", help="Override WhatsApp number")
    args = parser.parse_args()
    asyncio.run(_send(args.meeting_id, number=args.number))


if __name__ == "__main__":
    main()
