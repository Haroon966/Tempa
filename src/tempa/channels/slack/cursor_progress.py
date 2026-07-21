"""Tempa-branded Slack status copy for Cursor jobs."""

from __future__ import annotations


def msg_working() -> str:
    return "_Tempa is working on it…_"


def msg_still_working(minutes: int) -> str:
    return f"_Tempa is still working on it… ({minutes}m)_"


def msg_waiting_ci() -> str:
    return "_Tempa is waiting for CI on your PR…_"


def msg_ci_red() -> str:
    return "_Tempa saw red CI on your PR — fixing from the failures…_"


def msg_queued(position: int) -> str:
    return f"_Tempa queued your ask (#{position}) — a slot frees up shortly…_"


def msg_done(pr_url: str) -> str:
    link = pr_url or "the PR"
    return f"_Tempa confirmed green CI. Your work is done on <{link}>._"


def msg_problem(err: str) -> str:
    e = (err or "unknown error").strip()
    if len(e) > 300:
        e = e[:297] + "..."
    return f"_Tempa hit a problem: {e}_"


def msg_needs_help(*, pr_url: str, attempts: int) -> str:
    link = pr_url or "the PR"
    return (
        f"_Tempa needs help after {attempts} fix attempts on <{link}>. "
        "Summary is on the PR — please take a look._"
    )


def msg_interrupted() -> str:
    return (
        "_Tempa restarted while working on your request — "
        "the previous run was interrupted. Please ask again if you still need it._"
    )


def wants_channel_post(text: str) -> bool:
    from tempa.channels.slack.cursor_pr import wants_channel_announce

    return wants_channel_announce(text)
