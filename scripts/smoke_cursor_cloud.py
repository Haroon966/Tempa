"""Live smoke: Cursor cloud against CT PR branch. Exit 0 on success."""
from __future__ import annotations

import asyncio
import sys
import time

from tempa.qa.cursor import cursor_configured, cursor_prompt


async def main() -> int:
    if not cursor_configured():
        print("FAIL: CURSOR_API_KEY missing", file=sys.stderr)
        return 2
    t0 = time.time()
    text = await cursor_prompt(
        "In Orenda-Project/compliancetracker on this branch, does "
        "server/services/pefsis-teacher-images.ts exist? Reply with exactly "
        "YES or NO and one short reason.",
        repo="Orenda-Project/compliancetracker",
        starting_ref="fix/pefsis-add-teacher-images-MC20-18770",
    )
    elapsed = time.time() - t0
    print("ELAPSED_SEC", round(elapsed, 1))
    print("REPLY_CHARS", len(text or ""))
    print("REPLY")
    print((text or "")[:1000])
    if not (text or "").strip():
        print("FAIL: empty reply", file=sys.stderr)
        return 1
    if "YES" not in text.upper() and "NO" not in text.upper():
        print("FAIL: expected YES/NO", file=sys.stderr)
        return 1
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
