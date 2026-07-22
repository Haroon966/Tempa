"""ADK coordinator + single-turn Task specialists for rag/gmail/calendar."""

from __future__ import annotations

from google.adk import Agent
from pydantic import BaseModel, Field

from tempa.adk.model import groq_litellm
from tempa.adk.tools import calendar_task, gmail_task, rag_search


class SpecialistInput(BaseModel):
    goal: str = Field(description="Concrete subtask for the specialist.")


class SpecialistOutput(BaseModel):
    result: str = Field(description="Specialist result text for the coordinator.")


def build_root_agent() -> Agent:
    model = groq_litellm()

    rag_agent = Agent(
        name="rag",
        model=model,
        mode="single_turn",
        description="Search Tempa memory and past context via RAG.",
        input_schema=SpecialistInput,
        output_schema=SpecialistOutput,
        instruction=(
            "You answer using Tempa memory. Call rag_search with the goal as task. "
            "Then call finish_task with result set to the tool output. No user chat."
        ),
        tools=[rag_search],
    )

    gmail_agent = Agent(
        name="gmail",
        model=model,
        mode="single_turn",
        description="Gmail search, drafts, and inbox summaries.",
        input_schema=SpecialistInput,
        output_schema=SpecialistOutput,
        instruction=(
            "Handle email tasks. Call gmail_task with the goal as task. "
            "Then call finish_task with result set to the tool output. No user chat."
        ),
        tools=[gmail_task],
    )

    calendar_agent = Agent(
        name="calendar",
        model=model,
        mode="single_turn",
        description="Google Calendar list/create/update for the user.",
        input_schema=SpecialistInput,
        output_schema=SpecialistOutput,
        instruction=(
            "Handle calendar tasks. Call calendar_task with the goal as task. "
            "Then call finish_task with result set to the tool output. No user chat."
        ),
        tools=[calendar_task],
    )

    return Agent(
        name="tempa_adk_coordinator",
        model=model,
        description="Tempa ADK spike coordinator for rag, gmail, and calendar.",
        sub_agents=[rag_agent, gmail_agent, calendar_agent],
        instruction=(
            "You are Tempa's coordinator. Delegate with request_task_rag, "
            "request_task_gmail, and/or request_task_calendar (goal=subtask). "
            "You may call multiple specialists. After they finish, reply to the "
            "user with a clear merged answer. Do not invent email or calendar data."
        ),
    )
