"""Map internal exceptions to short, actionable Slack copy.

Never paste raw git/Python stderr at teammates — log the detail, speak human.
"""

from __future__ import annotations

from typing import Any


class ChatError(Exception):
    def __init__(self, code: str, message: str, *, recoverable: bool = True) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": self.message,
            "code": self.code,
            "recoverable": self.recoverable,
        }


_GENERIC = (
    "Something went wrong on my side — please ask again in this thread. "
    "If it keeps happening, ping the Tempa owner."
)


def _norm(err: str | BaseException | None) -> str:
    if err is None:
        return ""
    if isinstance(err, BaseException):
        text = str(err).strip() or type(err).__name__
    else:
        text = str(err).strip()
    # Collapse multiline git advice into one line for matching.
    return " ".join(text.split())


def classify_exception(exc: Exception) -> dict[str, Any]:
    text = str(exc).lower()
    if "groq" in text or "api key" in text:
        return ChatError(
            "GROQ_UNAVAILABLE",
            "Groq API is unavailable — check your API key in Connections.",
        ).to_payload()
    if "gmail" in text and "not connected" in text:
        return ChatError(
            "GMAIL_NOT_CONNECTED",
            "Gmail is not connected — connect in Connections.",
        ).to_payload()
    if "calendar" in text and "not connected" in text:
        return ChatError(
            "CALENDAR_NOT_CONNECTED",
            "Google Calendar is not connected.",
        ).to_payload()
    if "whatsapp" in text and ("disconnect" in text or "qr" in text):
        return ChatError(
            "WHATSAPP_DISCONNECTED",
            "WhatsApp disconnected — scan QR in Connections.",
        ).to_payload()
    if "timeout" in text or "timed out" in text:
        return ChatError("TIMEOUT", "That took too long — please try again.").to_payload()
    if "cancel" in text:
        return ChatError("CANCELLED", "Run cancelled.", recoverable=False).to_payload()
    return ChatError("UNKNOWN", _GENERIC).to_payload()


def sanitize_user_error(err: str | BaseException | None) -> str:
    """Human Slack sentence for any Cursor/Slack failure. Never returns raw stderr."""
    text = _norm(err)
    lower = text.lower()

    if not text:
        return _GENERIC

    if "dubious ownership" in lower or "safe.directory" in lower:
        return (
            "I hit a temporary git setup issue on the server and tried to fix it. "
            "Please ask again in this thread."
        )
    if "timeouterror" in lower or lower == "timeout" or "timed out" in lower:
        return (
            "That took too long and I had to stop. "
            "Reply here to retry — shorter scope helps if it was a big ask."
        )
    if "cursor_api_key" in lower or "cursor api key" in lower or (
        "cursor" in lower and "not configured" in lower
    ):
        return "Cursor isn’t configured on Tempa yet — ask the owner to set `CURSOR_API_KEY`."
    if "local repo path" in lower or "local_cwd" in lower or (
        "not available" in lower and ("repo" in lower or "/repos" in lower)
    ):
        return (
            "I can’t reach the project checkout on the server. "
            "Ask the Tempa owner to check the Docker repo mount, then try again."
        )
    if "read-only" in lower or "read only" in lower:
        return (
            "The project checkout is read-only on the server, so I can’t push fixes. "
            "Ask the Tempa owner to remount it read-write."
        )
    if "git is not available" in lower:
        return "Git isn’t available inside Tempa right now — ask the owner to check the container."
    if "gh cli" in lower or ("gh " in lower and "not available" in lower):
        return "GitHub CLI isn’t available inside Tempa right now — ask the owner to check the container."
    if "worktree" in lower and ("fail" in lower or "error" in lower):
        return (
            "I couldn’t prepare an isolated worktree for this job. "
            "Please ask again; if it keeps failing, ping the Tempa owner."
        )
    if "permission denied" in lower or "eacces" in lower:
        return "I don’t have permission to write on the server checkout — ask the Tempa owner."
    if "rate limit" in lower or "429" in lower:
        return "I hit a rate limit — wait a minute and ask again."
    if "network" in lower or "connection refused" in lower or "name or service not known" in lower:
        return "I couldn’t reach an upstream service — try again in a moment."
    if "no claude runner" in lower or "claude code cli failed" in lower:
        return "I couldn’t reach the Claude runner — try again shortly, or ask the owner to check it."

    # Unknown: never echo raw exception text to teammates.
    return _GENERIC


def slack_problem_message(err: str | BaseException | None) -> str:
    """Italic Slack wrapper used by Cursor progress posts."""
    return f"_{sanitize_user_error(err)}_"
