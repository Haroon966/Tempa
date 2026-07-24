#!/usr/bin/env python3
"""One-time: finalize stranded keepers + delete silent junk local video."""
from __future__ import annotations

import asyncio

from tempa.meet.archive import _parse_transcript_jsonl
from tempa.meet.job_store import get_all_job_statuses, update_job_status
from tempa.meet.media import delete_local_meeting_video
from tempa.meet.quality import count_transcript_segments
from tempa.meet.service import repair_meeting_finalize
from tempa.settings import get_settings

KEEP = [
    "06788ab7-159c-45d5-9cbe-e0fc81888e35",
    "b82af804-d8c5-4445-8720-1358106c912a",
]
JUNK = "3088a3d7-2c43-4ea6-98f6-0d9927b3f3aa"


async def main() -> None:
    settings = get_settings()
    for mid in KEEP:
        safe = mid.replace("/", "_")
        tp = settings.meetings_dir / safe / "transcripts" / f"{safe}.jsonl"
        segs = 0
        if tp.exists():
            _, segments = _parse_transcript_jsonl(tp)
            segs = count_transcript_segments(segments)
        print(f"repair {mid[:8]} segments={segs}", flush=True)
        update_job_status(
            mid,
            status="interrupted",
            leave_reason="worker_interrupted",
            humans_seen=True,
            segment_count=segs,
        )
        try:
            record = await repair_meeting_finalize(mid, send_notifications=False)
            print(
                "  uploadable=%s yt=%s minutes=%s"
                % (record.get("uploadable"), record.get("youtube_url"), record.get("minutes_status")),
                flush=True,
            )
            st = get_all_job_statuses().get(mid, {})
            print("  job=%s segs=%s" % (st.get("status"), st.get("segment_count")), flush=True)
        except Exception as exc:
            print("  FAILED %s" % exc, flush=True)
    print("junk delete: %s" % delete_local_meeting_video(JUNK), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
