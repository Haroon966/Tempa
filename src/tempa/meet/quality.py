"""Durable meeting quality model shared by retry, YouTube, archive, and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Job / lifecycle terminal and in-flight statuses.
ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "finalizing", "interrupted"})
TERMINAL_COVERED_STATUSES = frozenset({"completed", "empty"})
LEAVE_REASONS = frozenset(
    {
        "no_humans",
        "call_ended",
        "calendar_duration",
        "hard_max",
        "error",
        "worker_interrupted",
        "never_recorded",
    }
)


@dataclass(frozen=True)
class MeetingQuality:
    humans_seen: bool
    segment_count: int
    leave_reason: str
    recording_started_at: str | None = None
    recording_ended_at: str | None = None

    @property
    def uploadable(self) -> bool:
        return meeting_is_uploadable(segment_count=self.segment_count, humans_seen=self.humans_seen)

    @property
    def terminal_status(self) -> str:
        """Job status after finalize: completed (speech) or empty (no speech)."""
        return "completed" if self.uploadable else "empty"

    def as_dict(self) -> dict[str, Any]:
        return {
            "humans_seen": self.humans_seen,
            "segment_count": self.segment_count,
            "leave_reason": self.leave_reason,
            "recording_started_at": self.recording_started_at,
            "recording_ended_at": self.recording_ended_at,
            "uploadable": self.uploadable,
        }


def meeting_is_uploadable(*, segment_count: int, humans_seen: bool = False) -> bool:
    """Speech segments are the durable proof of content worth uploading."""
    del humans_seen  # reserved for future policy; speech alone is authoritative
    return int(segment_count or 0) > 0


def count_transcript_segments(segments: list[dict[str, Any]] | None) -> int:
    if not segments:
        return 0
    return sum(1 for row in segments if isinstance(row, dict) and str(row.get("text") or "").strip())


def quality_from_parts(
    *,
    humans_seen: bool,
    segments: list[dict[str, Any]] | None,
    leave_reason: str,
    recording_started_at: str | None = None,
    recording_ended_at: str | None = None,
) -> MeetingQuality:
    reason = (leave_reason or "call_ended").strip() or "call_ended"
    return MeetingQuality(
        humans_seen=bool(humans_seen),
        segment_count=count_transcript_segments(segments),
        leave_reason=reason,
        recording_started_at=recording_started_at,
        recording_ended_at=recording_ended_at,
    )
