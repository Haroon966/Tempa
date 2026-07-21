"""E2E: Cursor thread handler with live Slack transcript + local CT repo."""
from __future__ import annotations

import asyncio
import sys

from tempa.channels.slack.cursor_threads import handle_cursor_thread_message, load_cursor_threads


async def main() -> int:
    load_cursor_threads.cache_clear()
    reply = await handle_cursor_thread_message(
        "In one short sentence for Slack: what does resolveTeacherImagesForPefsis do? "
        "Do not modify files.",
        {
            "slack_channel_id": "C0AV0MUTCJW",
            "slack_thread_ts": "1784541760.548649",
        },
    )
    print("REPLY_LEN", len(reply or ""))
    print(reply or "")
    if not (reply or "").strip():
        print("FAIL: empty", file=sys.stderr)
        return 1
    if reply.lower().startswith("cursor run failed") or "misconfigured" in reply.lower():
        print("FAIL: error reply", file=sys.stderr)
        return 1
    print("E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
