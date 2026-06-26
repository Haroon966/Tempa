"""Dynamic GitHub repo allowlist (dashboard / approved chat requests)."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from typing import Any

from tempa.qa.config import qa_data_dir

_lock = threading.Lock()
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def normalize_repo(repo: str) -> str | None:
    name = str(repo or "").strip().strip("/")
    if name.endswith(".git"):
        name = name[:-4]
    return name if _REPO_RE.match(name) else None


def _path():
    p = qa_data_dir() / "allowed_repos.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"repos": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"repos": []}
    except Exception:
        return {"repos": []}


def _write(data: dict[str, Any]) -> None:
    _path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_dynamic_repos() -> list[str]:
    with _lock:
        rows = list(_read().get("repos") or [])
    names: list[str] = []
    for row in rows:
        name = normalize_repo(str(row.get("repo") or ""))
        if name:
            names.append(name)
    return sorted(set(names))


def add_repo(repo: str, *, source: str = "dashboard") -> dict[str, Any]:
    name = normalize_repo(repo)
    if not name:
        raise ValueError("invalid_repo")
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        data = _read()
        rows = list(data.get("repos") or [])
        for row in rows:
            if normalize_repo(str(row.get("repo") or "")) == name:
                row["source"] = source
                row["updated_at"] = now
                data["repos"] = rows
                _write(data)
                return dict(row)
        record = {"repo": name, "source": source, "added_at": now, "updated_at": now}
        rows.append(record)
        data["repos"] = rows
        _write(data)
        return dict(record)


def remove_repo(repo: str) -> bool:
    name = normalize_repo(repo)
    if not name:
        return False
    with _lock:
        data = _read()
        rows = list(data.get("repos") or [])
        kept = [r for r in rows if normalize_repo(str(r.get("repo") or "")) != name]
        if len(kept) == len(rows):
            return False
        data["repos"] = kept
        _write(data)
        return True


def is_dynamic_repo(repo: str) -> bool:
    name = normalize_repo(repo)
    if not name:
        return False
    return name in list_dynamic_repos()
