from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tempa.settings import get_settings


def consent_path() -> Path:
    return get_settings().sessions_dir / "meet_consent.json"


def has_recording_consent() -> bool:
    path = consent_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("consented"))
    except Exception:
        return False


def grant_recording_consent() -> dict:
    path = consent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "consented": True,
        "granted_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def revoke_recording_consent() -> dict:
    path = consent_path()
    payload = {"consented": False, "revoked_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
