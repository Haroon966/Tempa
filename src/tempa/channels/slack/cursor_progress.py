"""Tempa-branded Slack status copy for agent jobs (Cursor engine is invisible)."""

from __future__ import annotations


def msg_working() -> str:
    return "_On it — I'll update this thread as I work._"


def msg_rumi_working() -> str:
    return (
        "_On it with *Rumi* — running the skills pack in the background. "
        "You'll get the full answer here; reply in this thread anytime to steer._"
    )


def msg_still_working(minutes: int) -> str:
    # Kept for tests/compat — live activity feed replaces heartbeat spam.
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


def msg_dead_pr_suggest(*, pr_url: str, state: str) -> str:
    link = pr_url or "that PR"
    label = (state or "closed").lower()
    return (
        f"That PR (<{link}>) is {label}. "
        "We should open a new PR for follow-up work — "
        "say “raise pr and fix …” if you want me to."
    )


def msg_dead_pr_new(*, pr_url: str, state: str) -> str:
    link = pr_url or "that PR"
    label = (state or "closed").lower()
    return f"_PR <{link}> is {label} — opening a new PR instead._"


def msg_problem(err: str) -> str:
    """User-facing failure — never paste raw git/Python stderr into Slack."""
    from tempa.core.chat_errors import slack_problem_message

    return slack_problem_message(err)


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


def msg_unavailable() -> str:
    return (
        "_Tempa’s agent runtime isn’t available right now — "
        "ask the owner to check Connections (agent API key), then ask again._"
    )


def msg_stopped() -> str:
    return "_Stopped._"


def msg_activity(*, steps: list[str], done: bool = False) -> str:
    """IDE-like live activity block (Tempa-branded)."""
    header = "*Tempa* · Done" if done else "*Tempa* · Working…"
    body = "\n".join(f"• {s}" for s in steps[-12:] if s.strip()) or "• Starting…"
    return f"{header}\n{body}"


def wants_channel_post(text: str) -> bool:
    from tempa.channels.slack.cursor_pr import wants_channel_announce

    return wants_channel_announce(text)
