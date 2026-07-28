from __future__ import annotations

import logging
from typing import Any

from tempa.channels.coolify.client import (
    app_url,
    coolify_enabled,
    create_application,
    find_app_by_repo,
    get_application,
    human_error,
    is_likely_private_error,
    looks_like_env_only,
    normalize_git_repository,
    parse_env_block,
    poll_deployment,
    set_envs,
    trigger_deploy,
)
from tempa.channels.coolify.drafts import (
    clear_draft,
    context_key_from_slack,
    has_active_draft,
    load_draft,
    save_draft,
)
from tempa.channels.coolify.intent import (
    DeployRequest,
    is_deploy_cancel,
    is_deploy_confirm,
    parse_deploy_request,
    wants_coolify_deploy,
    wants_coolify_status,
)
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def deploy_feature_enabled() -> bool:
    settings = get_settings()
    return settings.coolify_enabled and coolify_enabled()


def should_route_to_coolify_deploy(text: str, context: dict[str, Any] | None = None) -> bool:
    ctx = dict(context or {})
    if not deploy_feature_enabled():
        return False
    t = (text or "").strip()
    if not t:
        return False
    key = _context_key(ctx)
    if key and has_active_draft(key):
        draft = load_draft(key)
        if draft and _is_draft_followup(t, draft):
            return True
    return wants_coolify_deploy(t)


def _context_key(context: dict[str, Any]) -> str:
    channel = str(
        context.get("channel_id")
        or context.get("slack_channel_id")
        or context.get("slack_channel")
        or ""
    )
    thread = str(
        context.get("thread_ts")
        or context.get("slack_thread_ts")
        or ""
    )
    if not channel:
        return ""
    return context_key_from_slack(channel, thread)


def _is_draft_followup(text: str, draft: dict[str, Any]) -> bool:
    state = str(draft.get("state") or "")
    if is_deploy_confirm(text) or is_deploy_cancel(text):
        return True
    if state in {"awaiting_envs", "awaiting_confirm"}:
        return True
    if looks_like_env_only(text):
        return True
    return False


def _thread_repo_hint(context: dict[str, Any]) -> str:
    """Reuse repo from Cursor/thread context when user says deploy this."""
    try:
        from tempa.channels.slack.cursor_threads import thread_coding_context_blob
        from tempa.qa.github.parse import parse_github_target

        blob = thread_coding_context_blob(context) or ""
        target = parse_github_target(blob)
        if target and target.repo:
            return target.repo
    except Exception:
        pass
    return ""


def _merge_request(text: str, context: dict[str, Any], draft: dict[str, Any] | None) -> DeployRequest:
    req = parse_deploy_request(text)
    if draft:
        req.git_repository = req.git_repository or str(draft.get("git_repository") or "")
        req.git_branch = req.git_branch if req.git_branch != "main" or not draft.get("git_branch") else str(draft.get("git_branch") or "main")
        if draft.get("git_branch") and req.git_branch == "main" and "branch" not in (text or "").lower():
            req.git_branch = str(draft.get("git_branch") or "main")
        req.ports_exposes = req.ports_exposes if "port" in (text or "").lower() else str(draft.get("ports_exposes") or req.ports_exposes)
        if req.private is None and draft.get("private") is not None:
            req.private = bool(draft.get("private"))
        if draft.get("envs") and isinstance(draft["envs"], dict) and not req.envs:
            req.envs = {str(k): str(v) for k, v in draft["envs"].items()}
        elif req.envs and draft.get("envs") and isinstance(draft["envs"], dict):
            merged = {str(k): str(v) for k, v in draft["envs"].items()}
            merged.update(req.envs)
            req.envs = merged
        if draft.get("force"):
            req.force = True
        if draft.get("skip_envs"):
            req.skip_envs = True
    if not req.git_repository:
        req.git_repository = _thread_repo_hint(context)
    if looks_like_env_only(text):
        extra = parse_env_block(text)
        if extra:
            req.envs = {**(req.envs or {}), **extra}
    return req


def _preview_text(req: DeployRequest, *, existing: dict[str, Any] | None) -> str:
    repo = normalize_git_repository(req.git_repository)
    action = "Redeploy" if existing else "Deploy"
    lines = [
        f"*{action} on Coolify*",
        f"• Repo: `{repo}`",
        f"• Branch: `{req.git_branch or 'main'}`",
        f"• Port: `{req.ports_exposes or '3000'}`",
    ]
    if req.private:
        lines.append("• Access: private (SSH deploy key)")
    elif req.private is False:
        lines.append("• Access: public")
    if req.envs:
        keys = ", ".join(f"`{k}`" for k in list(req.envs)[:12])
        more = f" (+{len(req.envs) - 12} more)" if len(req.envs) > 12 else ""
        lines.append(f"• Env keys: {keys}{more}")
    else:
        lines.append("• Env: none (reply with `KEY=value` lines or say `no envs`)")
    if existing:
        url = app_url(existing)
        if url:
            lines.append(f"• Existing app: {url}")
    lines.append("Reply *yes* to deploy, or paste env vars / `cancel`.")
    return "\n".join(lines)


async def handle_coolify_deploy_message(text: str, context: dict[str, Any]) -> str | None:
    """Slack handler — confirm → create/redeploy → poll → URL. Quiet until done."""
    if not deploy_feature_enabled():
        return "Coolify isn't connected yet — add the base URL and API token under Connections."

    key = _context_key(context)
    draft = load_draft(key) if key else None
    t = (text or "").strip()

    if draft and is_deploy_cancel(t):
        if key:
            clear_draft(key)
        return "Cancelled — nothing deployed."

    req = _merge_request(t, context, draft)

    # Env-only reply while awaiting envs/confirm
    if draft and looks_like_env_only(t) and str(draft.get("state") or "") in {"awaiting_envs", "awaiting_confirm"}:
        req.envs = {**(draft.get("envs") or {}), **parse_env_block(t)}
        draft.update(
            {
                "state": "awaiting_confirm",
                "envs": req.envs,
                "git_repository": req.git_repository,
                "git_branch": req.git_branch,
                "ports_exposes": req.ports_exposes,
                "private": req.private,
                "force": req.force,
                "skip_envs": req.skip_envs,
            }
        )
        if key:
            save_draft(key, draft)
        existing = find_app_by_repo(req.git_repository) if req.git_repository else None
        return _preview_text(req, existing=existing)

    # "no envs" / confirm while gathering → deploy
    if draft and str(draft.get("state") or "") in {"awaiting_confirm", "awaiting_envs"}:
        if re_skip_envs(t):
            req.skip_envs = True
            draft["skip_envs"] = True
            draft["state"] = "awaiting_confirm"
            if key:
                save_draft(key, draft)
            if is_deploy_confirm(t) or re_skip_envs(t):
                return await _execute_deploy(_merge_request("yes", context, draft), key)
        if is_deploy_confirm(t):
            return await _execute_deploy(_merge_request(t, context, draft), key)

    # Status-only
    if wants_coolify_status(t) and not wants_coolify_deploy(t):
        return _status_reply(req)

    if not req.git_repository:
        return "Which repo? Paste a `github.com/owner/repo` link (or `owner/repo`) and say deploy."

    # Fresh deploy intent — find existing, ask confirm (and envs if none)
    try:
        existing = find_app_by_repo(req.git_repository)
    except Exception as exc:
        logger.warning("coolify list apps failed: %s", exc)
        return human_error(exc)

    if req.skip_envs or req.envs or (existing and not wants_fresh_env_prompt(t)):
        state = "awaiting_confirm"
    else:
        state = "awaiting_envs"

    if key:
        save_draft(
            key,
            {
                "state": state,
                "git_repository": normalize_git_repository(req.git_repository),
                "git_branch": req.git_branch or "main",
                "ports_exposes": req.ports_exposes or "3000",
                "private": req.private,
                "force": req.force,
                "skip_envs": req.skip_envs,
                "envs": req.envs,
                "existing_uuid": str((existing or {}).get("uuid") or ""),
            },
        )

    if state == "awaiting_envs":
        repo = normalize_git_repository(req.git_repository)
        return (
            f"Deploy `{repo}` on Coolify — paste env vars as `KEY=value` lines "
            f"(or say `no envs` / `yes` to continue without)."
        )
    return _preview_text(req, existing=existing)


def re_skip_envs(text: str) -> bool:
    lower = (text or "").lower()
    return any(p in lower for p in ("no env", "no envs", "skip env", "without env"))


def wants_fresh_env_prompt(text: str) -> bool:
    lower = (text or "").lower()
    return any(p in lower for p in ("with env", "set env", "update env", "new env"))


def _status_reply(req: DeployRequest) -> str:
    if not req.git_repository:
        return "Which app? Include the GitHub repo."
    try:
        app = find_app_by_repo(req.git_repository)
    except Exception as exc:
        return human_error(exc)
    if not app:
        return f"No Coolify app for `{normalize_git_repository(req.git_repository)}` yet — say deploy to create one."
    url = app_url(app) or "(no URL yet)"
    name = app.get("name") or normalize_git_repository(req.git_repository)
    status = app.get("status") or "unknown"
    return f"*{name}* — {status}\n{url}"


async def _execute_deploy(req: DeployRequest, draft_key: str) -> str:
    import asyncio

    if not req.git_repository:
        return "Missing repo — paste `github.com/owner/repo` and try again."

    repo = normalize_git_repository(req.git_repository)
    try:
        result = await asyncio.to_thread(_deploy_sync, req)
    except Exception as exc:
        logger.exception("coolify deploy failed for %s", repo)
        if draft_key:
            clear_draft(draft_key)
        # Retry once as private if public create failed with auth-ish error
        if req.private is not True and is_likely_private_error(exc):
            try:
                req.private = True
                result = await asyncio.to_thread(_deploy_sync, req)
            except Exception as exc2:
                logger.exception("coolify private retry failed for %s", repo)
                return human_error(exc2)
        else:
            return human_error(exc)

    if draft_key:
        clear_draft(draft_key)
    return result


def _deploy_sync(req: DeployRequest) -> str:
    repo = normalize_git_repository(req.git_repository)
    branch = req.git_branch or "main"
    ports = req.ports_exposes or "3000"
    existing = find_app_by_repo(repo)
    private = bool(req.private) if req.private is not None else False

    if existing:
        uuid = str(existing.get("uuid") or "")
        if req.envs:
            set_envs(uuid, req.envs)
        deployment_uuid = trigger_deploy(uuid, force=req.force)
        dep = poll_deployment(deployment_uuid)
        app = get_application(uuid)
        url = app_url(app)
        status = str(dep.get("status") or "")
        if any(k in status.lower() for k in ("failed", "error", "cancel")):
            return f"Redeploy of `{repo}` failed on Coolify. Check the deployment logs there and try again."
        return f"Redeployed `{repo}`" + (f"\n{url}" if url else "")

    # Create new
    try:
        app = create_application(
            git_repository=repo,
            git_branch=branch,
            private=private,
            ports_exposes=ports,
            envs=req.envs or None,
            instant_deploy=False,
        )
    except Exception:
        if private:
            raise
        # Public create failed (likely private repo) → deploy-key path
        app = create_application(
            git_repository=repo,
            git_branch=branch,
            private=True,
            ports_exposes=ports,
            envs=req.envs or None,
            instant_deploy=False,
        )
    uuid = str(app.get("uuid") or "")
    if req.envs:
        set_envs(uuid, req.envs)
    deployment_uuid = trigger_deploy(uuid, force=req.force)
    dep = poll_deployment(deployment_uuid)
    app = get_application(uuid)
    url = app_url(app)
    status = str(dep.get("status") or "")
    if any(k in status.lower() for k in ("failed", "error", "cancel", "timeout")):
        return f"Created `{repo}` on Coolify but the deploy didn't finish. Open Coolify and check logs."
    return f"Deployed `{repo}`" + (f"\n{url}" if url else "")
