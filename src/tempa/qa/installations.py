"""GitHub App installations registry."""

from __future__ import annotations

import json
import threading
from typing import Any

from tempa.qa.config import qa_data_dir

_lock = threading.Lock()


def _path():
    p = qa_data_dir() / "installations.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"installations": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"installations": []}
    except Exception:
        return {"installations": []}


def _write(data: dict[str, Any]) -> None:
    _path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_installations() -> list[dict[str, Any]]:
    with _lock:
        return list(_read().get("installations") or [])


def _repos_from_config() -> list[str]:
    from tempa.qa.config import load_qa_config
    from tempa.settings import get_settings

    repos: set[str] = set()
    env_repos = get_settings().github_repos.strip()
    if env_repos:
        for part in env_repos.split(","):
            name = part.strip()
            if name and "/" in name:
                repos.add(name)
    for entry in load_qa_config().get("repos") or []:
        name = str(entry).strip()
        if name and "/" in name:
            repos.add(name)
    return sorted(repos)


def list_repos() -> list[str]:
    from tempa.qa.allowed_repos import list_dynamic_repos

    repos: set[str] = set(_repos_from_config())
    repos.update(list_dynamic_repos())
    for inst in list_installations():
        for repo in inst.get("repos") or []:
            full = str(repo.get("full_name") or "")
            if full:
                repos.add(full)
    return sorted(repos)


def list_repos_detail() -> list[dict[str, Any]]:
    from tempa.qa.allowed_repos import list_dynamic_repos
    from tempa.qa.config import load_qa_config
    from tempa.settings import get_settings

    details: dict[str, dict[str, Any]] = {}

    env_repos = get_settings().github_repos.strip()
    if env_repos:
        for part in env_repos.split(","):
            name = part.strip()
            if name and "/" in name:
                details[name] = {"repo": name, "source": "env", "removable": False}

    for entry in load_qa_config().get("repos") or []:
        name = str(entry).strip()
        if name and "/" in name:
            details[name] = {"repo": name, "source": "config", "removable": False}

    for name in list_dynamic_repos():
        details[name] = {"repo": name, "source": "dashboard", "removable": True}

    for inst in list_installations():
        for repo in inst.get("repos") or []:
            full = str(repo.get("full_name") or "")
            if full:
                details[full] = {
                    "repo": full,
                    "source": "github_app",
                    "removable": False,
                }

    return [details[k] for k in sorted(details)]


def upsert_installation(installation_id: int, account: str, repos: list[dict[str, Any]]) -> None:
    with _lock:
        data = _read()
        items = list(data.get("installations") or [])
        found = False
        for item in items:
            if int(item.get("id") or 0) == installation_id:
                item["account"] = account
                item["repos"] = repos
                found = True
                break
        if not found:
            items.append({"id": installation_id, "account": account, "repos": repos})
        data["installations"] = items
        _write(data)


def remove_installation(installation_id: int) -> None:
    with _lock:
        data = _read()
        items = [i for i in (data.get("installations") or []) if int(i.get("id") or 0) != installation_id]
        data["installations"] = items
        _write(data)


def add_repos_to_installation(installation_id: int, repos: list[dict[str, Any]]) -> None:
    with _lock:
        data = _read()
        for item in data.get("installations") or []:
            if int(item.get("id") or 0) != installation_id:
                continue
            existing = {r.get("full_name"): r for r in (item.get("repos") or [])}
            for repo in repos:
                name = str(repo.get("full_name") or "")
                if name:
                    existing[name] = repo
            item["repos"] = list(existing.values())
        _write(data)


def remove_repos_from_installation(installation_id: int, repo_names: list[str]) -> None:
    with _lock:
        data = _read()
        remove_set = set(repo_names)
        for item in data.get("installations") or []:
            if int(item.get("id") or 0) != installation_id:
                continue
            item["repos"] = [r for r in (item.get("repos") or []) if r.get("full_name") not in remove_set]
        _write(data)


def installation_id_for_repo(repo: str) -> int | None:
    for inst in list_installations():
        for r in inst.get("repos") or []:
            if r.get("full_name") == repo:
                return int(inst.get("id") or 0)
    return None
