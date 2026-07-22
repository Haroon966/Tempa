"""Report finished user-requested QA jobs back to Slack / WhatsApp."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_USER_CHANNELS = frozenset(
    {
        "slack",
        "whatsapp",
        "coordinator",
        "dashboard",
        "qa_dashboard",
        "api",
        "github_comment",
    }
)


def user_requested_qa(job: dict[str, Any]) -> bool:
    channel = str(job.get("source_channel") or "")
    return channel in _USER_CHANNELS


def format_qa_job_done_reply(job: dict[str, Any], *, result: dict[str, Any] | None = None) -> str:
    """Short completion report for the requesting chat thread."""
    from tempa.qa.results_reply import format_qa_results_reply

    repo = str(job.get("repo") or "")
    pr_number = job.get("pr_number")
    status = str(job.get("status") or "completed")
    result = result or (job.get("result") if isinstance(job.get("result"), dict) else {}) or {}

    if status == "failed":
        err = str(job.get("error") or result.get("error") or "unknown error")
        target = f"PR #{pr_number} on `{repo}`" if pr_number else f"`{repo}`"
        return f"QA for {target} failed: {err[:300]}. Ask me to retry."

    body = format_qa_results_reply(repo)
    lines = [body]
    comment_url = str(result.get("comment_url") or "")
    if pr_number and comment_url:
        lines.append("")
        lines.append(f"Commented on PR #{pr_number}: {comment_url}")
    elif pr_number:
        lines.append("")
        lines.append(f"Review finished for PR #{pr_number} on `{repo}`.")
    return "\n".join(lines)


async def notify_qa_job_done(job: dict[str, Any], *, result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Post QA completion to the Slack thread (and WhatsApp) that requested it."""
    out: dict[str, Any] = {"slack": False, "whatsapp": False}
    if not user_requested_qa(job):
        return out

    text = format_qa_job_done_reply(job, result=result)
    channel_id = str(job.get("slack_channel_id") or "")
    thread_ts = str(job.get("slack_thread_ts") or "")
    if channel_id:
        try:
            from tempa.channels.slack.outbound import send_slack_message_sync

            send_slack_message_sync(
                channel_id,
                text,
                thread_ts=thread_ts,
                source_channel="qa_job",
            )
            out["slack"] = True
        except Exception:
            log.exception("qa.notify: Slack report failed for job %s", job.get("id"))

    wa_number = str(job.get("whatsapp_number") or "")
    source = str(job.get("source_channel") or "")
    if wa_number and source == "whatsapp":
        try:
            from tempa.channels.whatsapp.outbound import send_whatsapp_message

            await send_whatsapp_message(
                wa_number,
                text,
                source_channel="whatsapp_auto_reply",
            )
            out["whatsapp"] = True
        except Exception:
            log.exception("qa.notify: WhatsApp report failed for job %s", job.get("id"))

    return out
