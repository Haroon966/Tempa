from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from tempa.settings import get_settings


def _load_permissions() -> dict[str, Any]:
    settings = get_settings()
    path = settings.config_dir / "permissions.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    allowed_paths = []
    for entry in data.get("allowed_paths", []):
        expanded = os.path.expandvars(entry.replace("${TEMPA_DATA_DIR}", str(settings.tempa_data_dir)))
        allowed_paths.append(Path(expanded).resolve())
    data["_resolved_paths"] = allowed_paths
    return data


def _is_path_allowed(path: Path) -> bool:
    perms = _load_permissions()
    resolved = path.resolve()
    return any(resolved == base or base in resolved.parents for base in perms["_resolved_paths"])


def run_shell(command: str) -> dict[str, Any]:
    perms = _load_permissions()
    timeout = int(perms.get("shell_timeout_seconds", 60))
    allowed = set(perms.get("allowed_shell_commands", []))
    first_token = command.strip().split()[0] if command.strip() else ""
    if first_token not in allowed:
        return {"status": "error", "msg": f"Command not allowlisted: {first_token}"}
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(get_settings().tempa_data_dir),
        )
        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "msg": "Command timed out"}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}
