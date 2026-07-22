"""Live smoke: local Cursor against mounted Compliance Tracker checkout."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from tempa.qa.cursor import cursor_configured, cursor_prompt

CT = "/repos/compliancetracker"


async def main() -> int:
    if not cursor_configured():
        print("FAIL: CURSOR_API_KEY missing", file=sys.stderr)
        return 2
    target = Path(CT) / "server/services/pefsis-teacher-images.ts"
    if not target.is_file():
        print(f"FAIL: missing mounted file {target}", file=sys.stderr)
        return 2
    t0 = time.time()
    text = await cursor_prompt(
        "In this repo, does server/services/pefsis-teacher-images.ts exist? "
        "Reply with exactly YES or NO and one short reason. "
        "Do not modify files.",
        local_cwd=CT,
    )
    elapsed = time.time() - t0
    print("ELAPSED_SEC", round(elapsed, 1))
    print("REPLY_CHARS", len(text or ""))
    print("REPLY")
    print((text or "")[:1000])
    if not (text or "").strip():
        print("FAIL: empty reply", file=sys.stderr)
        return 1
    if "YES" not in text.upper():
        print("FAIL: expected YES", file=sys.stderr)
        return 1
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
