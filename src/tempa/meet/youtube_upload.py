from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from tempa.channels.calendar.client import YOUTUBE_UPLOAD_SCOPE, google_oauth_scopes
from tempa.meet.media import resolve_playable_video_path
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_ALLOWED_PRIVACY = frozenset({"private", "unlisted"})


def validate_youtube_privacy(privacy: str) -> str:
    cleaned = (privacy or "").strip().lower()
    if cleaned not in _ALLOWED_PRIVACY:
        raise ValueError(f"MEET_YOUTUBE_PRIVACY must be private or unlisted, not {privacy!r}")
    return cleaned


def build_upload_body(*, title: str, description: str, privacy: str) -> dict[str, Any]:
    return {
        "snippet": {"title": title[:100], "description": description[:5000]},
        "status": {"privacyStatus": validate_youtube_privacy(privacy)},
    }


def load_youtube_credentials() -> Credentials | None:
    from tempa.security.sessions import read_secret_file, secret_file_exists, write_secret_file

    if not secret_file_exists("google/token.json"):
        return None

    token_json = read_secret_file("google/token.json")
    if not token_json:
        return None

    token_data = json.loads(token_json)
    granted = list(token_data.get("scopes") or [])
    if YOUTUBE_UPLOAD_SCOPE not in granted:
        logger.warning("Google token missing youtube.upload scope — reconnect Google in dashboard")
        return None

    creds = Credentials.from_authorized_user_info(token_data)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        write_secret_file("google/token.json", creds.to_json())
    if not creds.valid:
        return None
    return creds


def _existing_youtube_id(meeting_id: str) -> str | None:
    settings = get_settings()
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    manifest = settings.meetings_dir / safe_id / "manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            vid = str(data.get("youtube_video_id") or "").strip()
            if vid:
                return vid
        except Exception:
            pass

    if not settings.db_path.exists():
        return None
    try:
        import sqlite3

        conn = sqlite3.connect(settings.db_path)
        row = conn.execute(
            "SELECT youtube_video_id FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        conn.close()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return None


# uploadStatus values that mean the source is NOT safely stored on YouTube.
_UNCONFIRMED_UPLOAD_STATUS = frozenset({"failed", "rejected", "deleted"})


def upload_meeting_video(
    video_path: Path,
    *,
    title: str,
    description: str,
    privacy: str,
) -> dict[str, Any]:
    creds = load_youtube_credentials()
    if not creds:
        raise RuntimeError("YouTube upload credentials unavailable")

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = build_upload_body(title=title, description=description, privacy=privacy)
    media = MediaFileUpload(
        str(video_path),
        chunksize=5 * 1024 * 1024,
        resumable=True,
        mimetype="video/mp4" if video_path.suffix.lower() == ".mp4" else "video/webm",
    )
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response: dict[str, Any] | None = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("YouTube upload %s%%", int(status.progress() * 100))

    video_id = str(response.get("id") or "")
    if not video_id:
        raise RuntimeError("YouTube upload returned no video id")

    # The resumable loop only completes once YouTube has the full file; treat any
    # non-failure uploadStatus (or an absent one) as confirmed = safe to drop local copy.
    upload_status = str((response.get("status") or {}).get("uploadStatus") or "").lower()
    confirmed = upload_status not in _UNCONFIRMED_UPLOAD_STATUS

    return {
        "youtube_video_id": video_id,
        "youtube_url": f"https://youtu.be/{video_id}",
        "status": upload_status or "uploaded",
        "confirmed": confirmed,
    }


def maybe_upload_meeting_to_youtube(
    meeting_id: str,
    title: str,
    *,
    meet_link: str = "",
    audio_path_hint: str = "",
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.meet_youtube_upload_enabled:
        return None

    existing = _existing_youtube_id(meeting_id)
    if existing:
        return {
            "youtube_video_id": existing,
            "youtube_url": f"https://youtu.be/{existing}",
            "status": "skipped",
        }

    video_path = resolve_playable_video_path(meeting_id, audio_path_hint=audio_path_hint)
    if not video_path or not video_path.exists() or video_path.stat().st_size < 50_000:
        logger.info("YouTube upload skipped for %s — no playable video", meeting_id)
        return None

    if not load_youtube_credentials():
        logger.warning("YouTube upload skipped for %s — no credentials", meeting_id)
        return {"status": "error", "error": "credentials_unavailable"}

    try:
        privacy = validate_youtube_privacy(settings.meet_youtube_privacy)
    except ValueError:
        logger.exception("Invalid MEET_YOUTUBE_PRIVACY for %s", meeting_id)
        return {"status": "error", "error": "invalid_privacy"}

    description_parts = [f"Tempa meeting {meeting_id}"]
    if meet_link:
        description_parts.append(f"Meet link: {meet_link}")
    description = "\n".join(description_parts)

    try:
        return upload_meeting_video(
            video_path,
            title=title or f"Meeting {meeting_id[:8]}",
            description=description,
            privacy=privacy,
        )
    except Exception as exc:
        logger.exception("YouTube upload failed for %s", meeting_id)
        return {"status": "error", "error": str(exc)}


def _meeting_ids_on_disk() -> list[str]:
    settings = get_settings()
    if not settings.meetings_dir.exists():
        return []
    return [p.name for p in settings.meetings_dir.iterdir() if p.is_dir()]


def count_pending_local_videos() -> int:
    """Meetings that still have a local video not yet on YouTube."""
    from tempa.meet.media import resolve_video_path

    pending = 0
    for meeting_id in _meeting_ids_on_disk():
        if _existing_youtube_id(meeting_id):
            continue
        video = resolve_video_path(meeting_id)
        if video and video.exists() and video.stat().st_size > 50_000:
            pending += 1
    return pending


def youtube_upload_status() -> dict[str, Any]:
    """Snapshot for the dashboard: is upload on, does the token have the scope, backlog size."""
    settings = get_settings()
    enabled = settings.meet_youtube_upload_enabled
    try:
        scope_ok = load_youtube_credentials() is not None
    except Exception:
        scope_ok = False
    return {
        "enabled": enabled,
        "privacy": settings.meet_youtube_privacy,
        "scope_ok": scope_ok,
        "pending_local_videos": count_pending_local_videos() if enabled else 0,
    }


async def backfill_youtube_uploads() -> dict[str, Any]:
    """Upload every meeting that still has a local video, then drop the local copy.

    Idempotent: meetings already on YouTube just get their leftover local video removed.
    """
    import asyncio

    settings = get_settings()
    if not settings.meet_youtube_upload_enabled:
        return {"status": "disabled", "total": 0, "uploaded": 0, "already": 0, "failed": 0}
    if not await asyncio.to_thread(load_youtube_credentials):
        return {"status": "no_credentials", "total": 0, "uploaded": 0, "already": 0, "failed": 0}

    from tempa.meet.archive import list_meetings, save_meeting_archive, write_meeting_artifacts
    from tempa.meet.media import delete_local_meeting_video, resolve_video_path

    meetings = await list_meetings()
    considered = uploaded = already = failed = 0
    for meeting in meetings:
        meeting_id = meeting.get("id")
        if not meeting_id:
            continue
        video = await asyncio.to_thread(resolve_video_path, meeting_id)
        if not video or not video.exists() or video.stat().st_size < 50_000:
            continue
        considered += 1

        yt = await asyncio.to_thread(
            maybe_upload_meeting_to_youtube,
            meeting_id,
            meeting.get("title") or f"Meeting {meeting_id[:8]}",
            meet_link=meeting.get("meet_link") or "",
            audio_path_hint=meeting.get("audio_path") or "",
        )
        if not yt or not yt.get("youtube_video_id"):
            failed += 1
            continue

        meeting["youtube_video_id"] = yt["youtube_video_id"]
        meeting["youtube_url"] = yt.get("youtube_url") or f"https://youtu.be/{yt['youtube_video_id']}"
        await save_meeting_archive(meeting)
        safe_id = meeting_id.replace("/", "_").replace("\\", "_")
        meeting_dir = settings.meetings_dir / safe_id
        await asyncio.to_thread(
            write_meeting_artifacts, meeting_dir, meeting, meeting.get("followups") or []
        )

        # Confirmed = freshly stored on YouTube; skipped = already there. Both mean local is safe to drop.
        if yt.get("confirmed") or yt.get("status") == "skipped":
            await asyncio.to_thread(delete_local_meeting_video, meeting_id)
            if yt.get("status") == "skipped":
                already += 1
            else:
                uploaded += 1
        else:
            failed += 1

    return {
        "status": "ok",
        "total": considered,
        "uploaded": uploaded,
        "already": already,
        "failed": failed,
    }
