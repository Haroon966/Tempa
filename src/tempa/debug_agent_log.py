"""Agent debug logging — NDJSON to session log file (debug mode only)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_LOG_PATHS = (
    Path("/app/data/debug-9e929f.log"),
    Path("/home/olufsen/tempa/.cursor/debug-9e929f.log"),
)
_SESSION = "9e929f"


def agent_log(
    *,
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    entry = {
        "sessionId": _SESSION,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(entry, default=str) + "\n"
    for path in _LOG_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            continue
    # #endregion
