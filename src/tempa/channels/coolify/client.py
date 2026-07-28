from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from tempa.channels.coolify.session import (
    load_coolify_api_token,
    load_coolify_session_config,
)
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_BUILD_PACK = "nixpacks"
_DEFAULT_PORTS = "3000"
_POLL_INTERVAL_S = 5.0
_POLL_TIMEOUT_S = 600.0


def coolify_configured() -> bool:
    cfg = load_coolify_session_config()
    return bool(cfg.get("base_url") and load_coolify_api_token())


def coolify_enabled() -> bool:
    return get_settings().coolify_enabled and coolify_configured()


def _base_url() -> str:
    return load_coolify_session_config()["base_url"].rstrip("/")


def _api_root() -> str:
    base = _base_url()
    if base.endswith("/api/v1"):
        return base
    return f"{base}/api/v1"


def coolify_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | list[Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    if not coolify_configured():
        raise RuntimeError("Coolify not configured")
    token = load_coolify_api_token()
    url = f"{_api_root()}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(method, url, headers=headers, json=json_body, params=params)
    if resp.status_code >= 400:
        detail = resp.text[:500]
        raise RuntimeError(f"Coolify API {resp.status_code}: {detail}")
    if not resp.content:
        return resp.status_code, {}
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text


def test_connection() -> dict[str, Any]:
    _, data = coolify_request("GET", "/version")
    version = data if isinstance(data, str) else (data.get("version") if isinstance(data, dict) else str(data))
    servers = list_servers()
    usable = [s for s in servers if s.get("is_usable") or s.get("is_reachable")]
    return {
        "status": "ok",
        "version": str(version).strip().strip('"'),
        "server_count": len(servers),
        "usable_servers": len(usable),
    }


def list_servers() -> list[dict[str, Any]]:
    _, data = coolify_request("GET", "/servers")
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    return []


def list_projects() -> list[dict[str, Any]]:
    _, data = coolify_request("GET", "/projects")
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    return []


def list_applications() -> list[dict[str, Any]]:
    _, data = coolify_request("GET", "/applications")
    if isinstance(data, list):
        return [a for a in data if isinstance(a, dict)]
    return []


def list_github_apps() -> list[dict[str, Any]]:
    _, data = coolify_request("GET", "/github-apps")
    if isinstance(data, list):
        return [g for g in data if isinstance(g, dict)]
    return []


def list_security_keys() -> list[dict[str, Any]]:
    _, data = coolify_request("GET", "/security/keys")
    if isinstance(data, list):
        return [k for k in data if isinstance(k, dict)]
    return []


def get_security_key(uuid: str) -> dict[str, Any]:
    _, data = coolify_request("GET", f"/security/keys/{uuid}")
    if isinstance(data, dict):
        return data
    raise RuntimeError("Unexpected Coolify security key response")


def resolve_github_app_uuid() -> str:
    cfg = load_coolify_session_config()
    if cfg.get("github_app_uuid"):
        return cfg["github_app_uuid"]
    apps = list_github_apps()
    if apps:
        return str(apps[0].get("uuid") or "")
    return ""


_DEPLOY_KEY_NAME = "tempa-git-deploy"


def resolve_deploy_key_uuid() -> str:
    cfg = load_coolify_session_config()
    if cfg.get("deploy_key_uuid"):
        return cfg["deploy_key_uuid"]
    for key in list_security_keys():
        name = str(key.get("name") or "").strip().lower()
        if name == _DEPLOY_KEY_NAME or "tempa" in name and "deploy" in name:
            return str(key.get("uuid") or "")
    return ""


def ensure_git_deploy_key() -> dict[str, str]:
    """Ensure a Coolify SSH key exists for private GitHub repos (deploy key).

    Returns {uuid, public_key}. Generates once and reuses.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    from tempa.channels.coolify.session import save_coolify_session_config

    existing_uuid = resolve_deploy_key_uuid()
    if existing_uuid:
        try:
            key = get_security_key(existing_uuid)
            pub = str(key.get("public_key") or "").strip()
            if pub:
                return {"uuid": existing_uuid, "public_key": pub}
        except Exception:
            pass
        for key in list_security_keys():
            if str(key.get("uuid") or "") == existing_uuid:
                pub = str(key.get("public_key") or "").strip()
                if pub:
                    return {"uuid": existing_uuid, "public_key": pub}

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "id_ed25519"
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(path),
                "-C",
                _DEPLOY_KEY_NAME,
            ],
            check=True,
            capture_output=True,
        )
        private_key = path.read_text(encoding="utf-8")
        public_key = path.with_suffix(".pub").read_text(encoding="utf-8").strip()

    _, data = coolify_request(
        "POST",
        "/security/keys",
        json_body={
            "name": _DEPLOY_KEY_NAME,
            "description": "Tempa private-repo deploy key (add as GitHub Deploy Key)",
            "private_key": private_key,
        },
    )
    uuid = ""
    if isinstance(data, dict):
        uuid = str(data.get("uuid") or "")
        if data.get("public_key"):
            public_key = str(data["public_key"]).strip()
    if not uuid:
        # Already exists — resolve by name
        for key in list_security_keys():
            if str(key.get("name") or "").strip().lower() == _DEPLOY_KEY_NAME:
                uuid = str(key.get("uuid") or "")
                public_key = str(key.get("public_key") or public_key).strip()
                break
    if not uuid:
        raise RuntimeError("Could not create Coolify deploy key")

    cfg = load_coolify_session_config()
    save_coolify_session_config(
        base_url=cfg.get("base_url") or _base_url(),
        server_uuid=cfg.get("server_uuid", ""),
        project_uuid=cfg.get("project_uuid", ""),
        github_app_uuid=cfg.get("github_app_uuid", ""),
        deploy_key_uuid=uuid,
    )
    return {"uuid": uuid, "public_key": public_key}


def install_github_deploy_key(git_repository: str, public_key: str) -> dict[str, Any]:
    """Add the Coolify public key as a read-only GitHub deploy key (uses Tempa GitHub auth)."""
    import httpx

    repo = normalize_git_repository(git_repository)
    if not repo or not public_key.strip():
        return {"status": "error", "reason": "repo and public_key required"}
    try:
        from tempa.qa.github.auth import get_github_token, github_configured
    except Exception:
        return {"status": "error", "reason": "GitHub auth unavailable"}
    if not github_configured():
        return {"status": "error", "reason": "GitHub not configured"}
    try:
        token = get_github_token(repo)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:200]}

    title = "Tempa Coolify deploy"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=30.0) as client:
        # Skip if an identical key already exists
        listed = client.get(f"https://api.github.com/repos/{repo}/keys", headers=headers)
        if listed.status_code == 200:
            for item in listed.json() if isinstance(listed.json(), list) else []:
                existing = str(item.get("key") or "").strip()
                if existing and existing.split()[:2] == public_key.split()[:2]:
                    return {"status": "ok", "action": "exists", "id": item.get("id")}
        resp = client.post(
            f"https://api.github.com/repos/{repo}/keys",
            headers=headers,
            json={"title": title, "key": public_key.strip(), "read_only": True},
        )
    if resp.status_code in (201, 200):
        data = resp.json() if resp.content else {}
        return {"status": "ok", "action": "created", "id": data.get("id")}
    if resp.status_code == 422 and "key is already in use" in resp.text.lower():
        return {"status": "ok", "action": "exists"}
    return {"status": "error", "reason": f"GitHub {resp.status_code}: {resp.text[:300]}"}


def normalize_git_repository(repo: str) -> str:
    """Return owner/repo (no .git, no github.com prefix)."""
    raw = (repo or "").strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    if "github.com/" in raw.lower():
        raw = raw.split("github.com/", 1)[1]
    if raw.startswith("git@"):
        # git@github.com:owner/repo
        raw = raw.split(":", 1)[-1]
    parts = [p for p in raw.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return raw


def git_repository_url(repo: str, *, ssh: bool = False) -> str:
    """Coolify 4.x requires https:// or git@ URLs, not bare owner/repo."""
    owner_repo = normalize_git_repository(repo)
    if not owner_repo:
        return ""
    if ssh:
        return f"git@github.com:{owner_repo}.git"
    return f"https://github.com/{owner_repo}"


def find_app_by_repo(git_repository: str) -> dict[str, Any] | None:
    target = normalize_git_repository(git_repository).lower()
    for app in list_applications():
        repo = normalize_git_repository(str(app.get("git_repository") or "")).lower()
        if repo and repo == target:
            return app
    return None


def get_application(uuid: str) -> dict[str, Any]:
    _, data = coolify_request("GET", f"/applications/{uuid}")
    if isinstance(data, dict):
        return data
    raise RuntimeError("Unexpected Coolify application response")


def get_deployment(uuid: str) -> dict[str, Any]:
    _, data = coolify_request("GET", f"/deployments/{uuid}")
    if isinstance(data, dict):
        return data
    raise RuntimeError("Unexpected Coolify deployment response")


def resolve_server_uuid() -> str:
    cfg = load_coolify_session_config()
    if cfg.get("server_uuid"):
        return cfg["server_uuid"]
    servers = list_servers()
    for s in servers:
        if s.get("is_coolify_host") and (s.get("is_usable") or s.get("is_reachable")):
            return str(s.get("uuid") or "")
    for s in servers:
        if s.get("is_usable") or s.get("is_reachable"):
            return str(s.get("uuid") or "")
    if servers:
        return str(servers[0].get("uuid") or "")
    raise RuntimeError("No Coolify servers available")


def resolve_project_uuid(*, name: str = "Tempa Deploys") -> str:
    cfg = load_coolify_session_config()
    if cfg.get("project_uuid"):
        return cfg["project_uuid"]
    projects = list_projects()
    for p in projects:
        if str(p.get("name") or "").strip().lower() == name.lower():
            return str(p.get("uuid") or "")
    if projects:
        return str(projects[0].get("uuid") or "")
    _, data = coolify_request(
        "POST",
        "/projects",
        json_body={"name": name, "description": "Apps deployed via Tempa"},
    )
    if isinstance(data, dict) and data.get("uuid"):
        return str(data["uuid"])
    projects = list_projects()
    for p in projects:
        if str(p.get("name") or "").strip().lower() == name.lower():
            return str(p.get("uuid") or "")
    raise RuntimeError("Could not resolve Coolify project")


def resolve_environment_uuid(project_uuid: str, *, name: str = "production") -> str:
    _, data = coolify_request("GET", f"/projects/{project_uuid}/environments")
    envs: list[dict[str, Any]] = []
    if isinstance(data, list):
        envs = [e for e in data if isinstance(e, dict)]
    elif isinstance(data, dict):
        nested = data.get("environments") or data.get("data") or []
        if isinstance(nested, list):
            envs = [e for e in nested if isinstance(e, dict)]
    for e in envs:
        if str(e.get("name") or "").strip().lower() == name.lower():
            return str(e.get("uuid") or "")
    if envs:
        return str(envs[0].get("uuid") or "")
    raise RuntimeError(f"No environment found for project {project_uuid}")


def app_subdomain_url(app_name: str, git_repository: str = "") -> str:
    """Build https://{slug}.wildcard from settings, or empty if unset."""
    from tempa.settings import get_settings

    base = (get_settings().coolify_wildcard_domain or "").strip().lower()
    base = base.removeprefix("https://").removeprefix("http://").strip("/")
    if not base:
        return ""
    slug = (app_name or "").strip().lower()
    if not slug and git_repository:
        slug = normalize_git_repository(git_repository).replace("/", "-").lower()
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug:
        return ""
    return f"https://{slug}.{base}"


def create_application(
    *,
    git_repository: str,
    git_branch: str = "main",
    name: str = "",
    private: bool = False,
    ports_exposes: str = _DEFAULT_PORTS,
    build_pack: str = _DEFAULT_BUILD_PACK,
    envs: dict[str, str] | None = None,
    instant_deploy: bool = False,
) -> dict[str, Any]:
    repo = normalize_git_repository(git_repository)
    server_uuid = resolve_server_uuid()
    project_uuid = resolve_project_uuid()
    environment_uuid = resolve_environment_uuid(project_uuid)
    app_name = name.strip() or repo.replace("/", "-")
    body: dict[str, Any] = {
        "project_uuid": project_uuid,
        "server_uuid": server_uuid,
        "environment_uuid": environment_uuid,
        "git_branch": git_branch or "main",
        "build_pack": build_pack or _DEFAULT_BUILD_PACK,
        "ports_exposes": ports_exposes or _DEFAULT_PORTS,
        "name": app_name,
        "instant_deploy": bool(instant_deploy),
        "autogenerate_domain": True,
    }
    custom = app_subdomain_url(app_name, repo)
    if custom:
        body["domains"] = custom
        body["autogenerate_domain"] = False
    if private:
        # Prefer SSH deploy key (no Coolify GitHub App required).
        deploy = ensure_git_deploy_key()
        install = install_github_deploy_key(repo, deploy["public_key"])
        if install.get("status") != "ok":
            raise RuntimeError(
                "Deploy key ready in Coolify, but GitHub rejected adding it. "
                f"Add this read-only Deploy Key on github.com/{repo}/settings/keys then retry:\n"
                f"`{deploy['public_key']}`"
                + (f"\n({install.get('reason', '')})" if install.get("reason") else "")
            )
        body["private_key_uuid"] = deploy["uuid"]
        body["git_repository"] = git_repository_url(repo, ssh=True)
        path = "/applications/private-deploy-key"
    else:
        body["git_repository"] = git_repository_url(repo)
        path = "/applications/public"
    _, data = coolify_request("POST", path, json_body=body)
    uuid = ""
    if isinstance(data, dict):
        uuid = str(data.get("uuid") or "")
    if not uuid:
        found = find_app_by_repo(repo)
        if found:
            uuid = str(found.get("uuid") or "")
    if not uuid:
        raise RuntimeError("Coolify created the app but returned no UUID")
    if envs:
        set_envs(uuid, envs)
    return get_application(uuid)


def set_envs(app_uuid: str, envs: dict[str, str]) -> None:
    if not envs:
        return
    payload = {
        "data": [
            {"key": str(k), "value": str(v), "is_literal": True}
            for k, v in envs.items()
            if str(k).strip()
        ]
    }
    if not payload["data"]:
        return
    coolify_request("PATCH", f"/applications/{app_uuid}/envs/bulk", json_body=payload)


def trigger_deploy(app_uuid: str, *, force: bool = False) -> str:
    _, data = coolify_request(
        "POST",
        "/deploy",
        params={"uuid": app_uuid, "force": str(bool(force)).lower()},
    )
    if isinstance(data, dict):
        deployments = data.get("deployments") or []
        if isinstance(deployments, list) and deployments:
            first = deployments[0]
            if isinstance(first, dict) and first.get("deployment_uuid"):
                return str(first["deployment_uuid"])
        if data.get("deployment_uuid"):
            return str(data["deployment_uuid"])
    raise RuntimeError("Coolify deploy did not return a deployment UUID")


def _deployment_finished(status: str) -> bool:
    s = (status or "").lower()
    return any(
        k in s
        for k in (
            "finished",
            "success",
            "successful",
            "failed",
            "error",
            "cancelled",
            "canceled",
            "exited",
        )
    )


def _deployment_failed(status: str) -> bool:
    s = (status or "").lower()
    return any(k in s for k in ("failed", "error", "cancelled", "canceled"))


def poll_deployment(deployment_uuid: str, *, timeout_s: float = _POLL_TIMEOUT_S) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = get_deployment(deployment_uuid)
        status = str(last.get("status") or "")
        if _deployment_finished(status):
            return last
        time.sleep(_POLL_INTERVAL_S)
    return last or {"status": "timeout", "uuid": deployment_uuid}


def app_url(app: dict[str, Any]) -> str:
    fqdn = str(app.get("fqdn") or "").strip()
    if fqdn:
        # Coolify may store comma-separated or scheme-less hosts
        host = fqdn.split(",")[0].strip()
        if host.startswith("http://") or host.startswith("https://"):
            return host
        return f"https://{host}"
    domains = str(app.get("domains") or "").strip()
    if domains:
        host = domains.split(",")[0].strip()
        if host.startswith("http://") or host.startswith("https://"):
            return host
        return f"http://{host}"
    return ""


def human_error(exc: BaseException) -> str:
    msg = str(exc)
    if "Deploy Key" in msg or "deploy key" in msg.lower() or (
        "github.com/" in msg and "settings/keys" in msg
    ):
        return msg[:800]
    if "401" in msg or "Unauthenticated" in msg:
        return "Coolify API token rejected — reconnect in Connections."
    if "GitHub App" in msg:
        return msg
    if "Coolify API" in msg:
        return "Coolify deploy failed — check the app in Coolify and try again."
    return "Coolify is unavailable right now — try again in a moment."


def parse_env_block(text: str) -> dict[str, str]:
    """Parse KEY=value lines from a message (ignores comments/blank)."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or " " in key:
            continue
        # skip accidental prose lines
        if not key.replace("_", "").isalnum():
            continue
        out[key] = value
    return out


def looks_like_env_only(text: str) -> bool:
    t = (text or "").strip()
    if not t or "\n" not in t and "=" not in t:
        return False
    envs = parse_env_block(t)
    if not envs:
        return False
    # Most non-empty lines should be KEY=value
    lines = [ln.strip() for ln in t.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return len(envs) >= max(1, len(lines) // 2)


def is_likely_private_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("private", "404", "not found", "authentication", "permission", "403"))


def repo_display_name(git_repository: str) -> str:
    return normalize_git_repository(git_repository)


def base_host() -> str:
    try:
        return urlparse(_base_url()).netloc or _base_url()
    except Exception:
        return _base_url()
