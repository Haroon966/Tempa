from __future__ import annotations

import re
from dataclasses import dataclass, field

from tempa.qa.github.parse import parse_github_target

_DEPLOY_RE = re.compile(
    r"\b("
    r"deploy|"
    r"redeploy|"
    r"coolify|"
    r"host\s+(this|it|the\s+app)|"
    r"ship\s+(this|it|to\s+coolify)|"
    r"put\s+(this|it)\s+(live|online|on\s+(coolify|this\s+machine|the\s+server))"
    r")\b",
    re.I,
)

_STATUS_RE = re.compile(
    r"\b("
    r"deploy(ment)?\s+status|"
    r"coolify\s+status|"
    r"is\s+it\s+(live|deployed|up)|"
    r"app\s+url|"
    r"deployment\s+url"
    r")\b",
    re.I,
)

_CONFIRM_RE = re.compile(
    r"^\s*(yes|yep|yeah|y|go|deploy(\s+it)?|lgtm|confirm|looks\s+good|ship\s+it|do\s+it)\s*[!.]*\s*$",
    re.I,
)

_CANCEL_RE = re.compile(
    r"\b(never\s+mind|cancel|abort|stop|don't\s+deploy|do\s+not\s+deploy)\b",
    re.I,
)

_BRANCH_RE = re.compile(r"\b(?:branch|on)\s+[`'\"]?([A-Za-z0-9._/\-]+)[`'\"]?", re.I)
_PORT_RE = re.compile(r"\bport\s+(\d{2,5})\b", re.I)
_PRIVATE_RE = re.compile(r"\b(private|deploy\s+key|with\s+deploy\s+key|with\s+github\s+app)\b", re.I)
_PUBLIC_RE = re.compile(r"\bpublic\b", re.I)
_FORCE_RE = re.compile(r"\b(force(\s+rebuild)?|no\s+cache)\b", re.I)
_SKIP_ENV_RE = re.compile(r"\b(no\s+envs?|skip\s+envs?|without\s+envs?)\b", re.I)


@dataclass
class DeployRequest:
    git_repository: str = ""
    git_branch: str = "main"
    ports_exposes: str = "3000"
    private: bool | None = None
    force: bool = False
    skip_envs: bool = False
    envs: dict[str, str] = field(default_factory=dict)
    status_only: bool = False


def wants_coolify_deploy(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _STATUS_RE.search(t):
        return True
    if not _DEPLOY_RE.search(t):
        return False
    # Require a repo ref OR coolify keyword (status/list handled separately)
    lower = t.lower()
    if "coolify" in lower:
        return True
    target = parse_github_target(t)
    if target and target.repo:
        return True
    # "deploy this" in a thread that already has a repo is handled via context
    if re.search(r"\bdeploy\s+(this|it|again)\b", t, re.I):
        return True
    return False


def wants_coolify_status(text: str) -> bool:
    return bool(_STATUS_RE.search(text or ""))


def is_deploy_confirm(text: str) -> bool:
    return bool(_CONFIRM_RE.match(text or ""))


def is_deploy_cancel(text: str) -> bool:
    return bool(_CANCEL_RE.search(text or ""))


def parse_deploy_request(text: str) -> DeployRequest:
    t = (text or "").strip()
    req = DeployRequest()
    target = parse_github_target(t)
    if target and target.repo:
        req.git_repository = target.repo
        if target.branch:
            req.git_branch = target.branch
    m = _BRANCH_RE.search(t)
    if m and m.group(1).lower() not in {"the", "this", "our", "my"}:
        req.git_branch = m.group(1)
    m = _PORT_RE.search(t)
    if m:
        req.ports_exposes = m.group(1)
    if _PRIVATE_RE.search(t):
        req.private = True
    elif _PUBLIC_RE.search(t):
        req.private = False
    req.force = bool(_FORCE_RE.search(t))
    req.skip_envs = bool(_SKIP_ENV_RE.search(t))
    req.status_only = wants_coolify_status(t) and not bool(_DEPLOY_RE.search(t) and "status" not in t.lower())
    from tempa.channels.coolify.client import parse_env_block

    req.envs = parse_env_block(t)
    return req
