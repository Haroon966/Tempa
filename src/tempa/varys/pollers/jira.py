from __future__ import annotations

import logging

from tempa.channels.jira.client import jira_enabled, poll_updated_issues
from tempa.varys.config import load_varys_config

logger = logging.getLogger(__name__)


def _project_keys() -> list[str]:
    cfg = load_varys_config()
    keys = [k for k in cfg.jira_projects if k]
    if keys:
        return keys
    from tempa.channels.jira.session import load_jira_session_config

    default = load_jira_session_config().get("default_project", "")
    return [default] if default else []


def poll_repos(since_iso: str) -> list[dict]:
    if not jira_enabled():
        return []
    projects = _project_keys()
    try:
        return poll_updated_issues(projects, since_iso)
    except Exception as exc:
        logger.warning("Jira issue poll failed: %s", exc)
        return []
