"""Domain models and shared exceptions for meeting-lens."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MeetingLensError(Exception):
    """Base error for all expected meeting-lens failures."""


class ParseError(MeetingLensError):
    """Raised when transcript content cannot be parsed."""


class BackendError(MeetingLensError):
    """Raised when an LLM backend call or response parsing fails."""


class FormatError(MeetingLensError):
    """Raised when formatting output fails."""


class Sentiment(str, Enum):
    """Overall sentiment for a meeting conversation."""

    positive = "positive"
    neutral = "neutral"
    mixed = "mixed"
    negative = "negative"


class ActionItem(BaseModel):
    """A concrete task assigned during the meeting."""

    owner: str | None = Field(default=None, description="Person responsible, if named.")
    task: str
    due: str | None = Field(default=None, description="Due date or time if mentioned.")


class Decision(BaseModel):
    """A decision reached during the meeting."""

    summary: str
    made_by: str | None = Field(default=None, description="Person or group making the decision.")


class OpenQuestion(BaseModel):
    """A question left unresolved in the meeting."""

    question: str
    raised_by: str | None = Field(default=None, description="Person who raised the question.")


class MeetingSummary(BaseModel):
    """Structured summary output produced from a meeting transcript."""

    title: str | None = Field(default=None, description="Inferred title from content.")
    date: str | None = Field(default=None, description="Inferred date if present.")
    participants: list[str] = Field(default_factory=list)
    tldr: str
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    sentiment: Sentiment
    sentiment_notes: str
