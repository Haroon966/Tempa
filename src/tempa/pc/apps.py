from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any


def open_app(name_or_path: str) -> dict[str, Any]:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-a", name_or_path], check=True, capture_output=True)
        elif shutil.which("xdg-open"):
            subprocess.run(["xdg-open", name_or_path], check=True, capture_output=True)
        else:
            subprocess.run([name_or_path], check=True, capture_output=True)
        return {"status": "success", "opened": name_or_path}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


def close_app(name: str) -> dict[str, Any]:
    """FR-PC-01: close application by name."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'tell application "{name}" to quit'], check=True, capture_output=True)
        elif sys.platform == "win32":
            subprocess.run(["taskkill", "/IM", f"{name}.exe", "/F"], check=True, capture_output=True)
        else:
            subprocess.run(["pkill", "-f", name], check=True, capture_output=True)
        return {"status": "success", "closed": name}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}
