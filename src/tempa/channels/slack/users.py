from __future__ import annotations

from tempa.settings import get_settings

from tempa.channels.slack.messages import GUEST_PRIVATE_COMING_SOON

__all__ = [
    "GUEST_PRIVATE_COMING_SOON",
    "get_owner_slack_user_id",
    "get_allowed_slack_user_ids",
    "is_allowed_slack_user",
    "is_privileged_slack_user",
]


def get_owner_slack_user_id() -> str:
    return get_settings().slack_owner_user_id.strip()


def get_allowed_slack_user_ids() -> set[str]:
    raw = get_settings().slack_allowed_user_ids.strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_allowed_slack_user(user_id: str) -> bool:
    if not user_id:
        return False
    if get_settings().slack_allow_all:
        return True
    owner = get_owner_slack_user_id()
    if owner and user_id == owner:
        return True
    return user_id in get_allowed_slack_user_ids()


def is_privileged_slack_user(user_id: str) -> bool:
    return is_allowed_slack_user(user_id)
