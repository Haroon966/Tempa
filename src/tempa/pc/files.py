from __future__ import annotations

import itertools
import os
from pathlib import Path
from typing import Any

from tempa.pc.shell import _is_path_allowed
from tempa.settings import get_settings


def read_file(path: str, start: int = 1, count: int = 200) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not _is_path_allowed(target):
        return {"status": "error", "msg": f"Path not allowed: {target}"}
    if not target.exists():
        return {"status": "error", "msg": "File not found"}
    try:
        with target.open(encoding="utf-8", errors="replace") as f:
            lines = list(itertools.islice(f, start - 1, start - 1 + count))
        content = "".join(lines)
        return {"status": "success", "path": str(target), "content": content}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


def write_file(path: str, content: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not _is_path_allowed(target):
        return {"status": "error", "msg": f"Path not allowed: {target}"}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"status": "success", "path": str(target)}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


def create_directory(path: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not _is_path_allowed(target):
        return {"status": "error", "msg": f"Path not allowed: {target}"}
    try:
        target.mkdir(parents=True, exist_ok=True)
        return {"status": "success", "path": str(target)}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


def delete_path(path: str) -> dict[str, Any]:
    import yaml

    target = Path(path).expanduser().resolve()
    if not _is_path_allowed(target):
        return {"status": "error", "msg": f"Path not allowed: {target}"}

    perms_path = get_settings().config_dir / "permissions.yaml"
    with perms_path.open(encoding="utf-8") as f:
        perms = yaml.safe_load(f) or {}
    delete_allowed = perms.get("allowed_delete_paths") or []
    if not delete_allowed:
        return {"status": "error", "msg": "Delete operations disabled. Add paths to allowed_delete_paths in permissions.yaml"}

    resolved_delete: list[Path] = []
    for entry in delete_allowed:
        expanded = os.path.expandvars(entry.replace("${TEMPA_DATA_DIR}", str(get_settings().tempa_data_dir)))
        resolved_delete.append(Path(expanded).resolve())
    if not any(target == base or base in target.parents for base in resolved_delete):
        return {"status": "error", "msg": f"Delete not allowed for path: {target}"}

    if not target.exists():
        return {"status": "error", "msg": "Path not found"}
    try:
        if target.is_dir():
            if any(target.iterdir()):
                return {"status": "error", "msg": "Directory not empty (non-recursive delete)"}
            target.rmdir()
        else:
            target.unlink()
        return {"status": "success", "path": str(target)}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}


def patch_file(path: str, old_content: str, new_content: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not _is_path_allowed(target):
        return {"status": "error", "msg": f"Path not allowed: {target}"}
    if not target.exists():
        return {"status": "error", "msg": "File not found"}
    text = target.read_text(encoding="utf-8")
    count = text.count(old_content)
    if count != 1:
        return {"status": "error", "msg": f"Expected exactly one match, found {count}"}
    target.write_text(text.replace(old_content, new_content), encoding="utf-8")
    return {"status": "success", "path": str(target)}
