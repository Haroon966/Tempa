from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_plan_subtasks_multi_intent_short_message():
    from tempa.agents.specialists import plan_subtasks

    msg = "join https://meet.google.com/abc-defg-hij and remind the team on WhatsApp"
    with patch("tempa.agents.specialists.get_router") as get_router:
        router = MagicMock()
        router.chat_completion.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content='{"subtasks": ['
                        '{"agent": "rag", "task": "context"}, '
                        '{"agent": "meet", "task": "join meet"}, '
                        '{"agent": "channel", "task": "remind team"}'
                        "]}"
                    )
                )
            ]
        )
        get_router.return_value = router

        subtasks = plan_subtasks(msg, {})
        agents = {t["agent"] for t in subtasks}
        assert "meet" in agents
        assert "channel" in agents
        router.chat_completion.assert_called_once()


def test_plan_subtasks_heuristic_for_simple_chat():
    from tempa.agents.specialists import plan_subtasks

    subtasks = plan_subtasks("hello there", {})
    assert subtasks == [{"agent": "rag", "task": "hello there"}]


@pytest.mark.asyncio
async def test_rag_gate_whatsapp_uses_agentic_rag():
    from tempa.agents.graph import rag_gate_node

    with patch(
        "tempa.agents.graph.run_rag_agent_task",
        new_callable=AsyncMock,
        return_value=("Graded memory answer", []),
    ) as rag_task:
        state = {
            "user_message": "what did we decide Tuesday?",
            "rag_task": {"agent": "rag", "task": "retrieve Tuesday context"},
            "context": {"channel": "whatsapp"},
        }
        result = await rag_gate_node(state)

    rag_task.assert_awaited_once()
    call_context = rag_task.call_args.args[1]
    assert call_context["channel"] == "whatsapp"
    assert result["results"]["rag"] == "Graded memory answer"
    assert result["context"]["rag_context"] == "Graded memory answer"


def test_verifier_blocks_false_email_sent():
    from tempa.router.verifier import verify_reply

    pack = {
        "action_facts": ['[gmail] status=pending'],
        "conversation_thread": "",
        "memory_answer": "",
    }
    ok, corrected = verify_reply("Done! I sent the email to the team.", pack)
    assert ok is False
    assert "pending" in corrected.lower() or "prepared" in corrected.lower() or "status" in corrected.lower()


def test_verifier_allows_factual_reply():
    from tempa.router.verifier import verify_reply

    pack = {
        "action_facts": ["Joining Google Meet now (job meet-1)."],
        "conversation_thread": "",
        "memory_answer": "",
    }
    ok, reply = verify_reply("Joining Google Meet now (job meet-1).", pack)
    assert ok is True
    assert reply == "Joining Google Meet now (job meet-1)."


@pytest.mark.asyncio
async def test_merge_includes_grounding():
    from tempa.agents.specialists import merge_results

    with patch("tempa.agents.specialists.get_router") as get_router:
        router = MagicMock()
        router.chat_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Merged reply"))]
        )
        get_router.return_value = router

        reply, _sources = await merge_results(
            "what is on my calendar?",
            {"calendar": '{"events": []}', "rag": "standup at 9am"},
            {"channel": "extension", "rag_context": "standup at 9am"},
        )
        assert reply == "Merged reply"

    prompt = router.chat_completion.call_args.kwargs["messages"][0]["content"]
    assert "Grounding facts" in prompt
    assert "standup at 9am" in prompt
    assert "Agent results JSON" in prompt


def test_whatsapp_calendar_followup_grounded():
    from tempa.agents.grounding import build_grounding_pack, format_grounding_for_prompt

    with (
        patch("tempa.channels.whatsapp.conversation.get_recent_messages") as get_recent,
        patch("tempa.channels.calendar.events.fetch_upcoming_summary") as fetch_cal,
    ):
        get_recent.return_value = [
            {"role": "user", "text": "what meetings today?"},
            {"role": "assistant", "text": "You have a standup at 9am."},
        ]
        fetch_cal.return_value = "Upcoming: Standup 9:00 AM, Review 2:00 PM"

        pack = build_grounding_pack(
            "what meeting name?",
            {"channel": "whatsapp", "whatsapp_number": "+1234"},
            include_calendar=True,
            memory_answer="Previous standup notes",
        )
        prompt = format_grounding_for_prompt(pack, owner="+1234")

    assert "Standup" in prompt
    assert "what meeting name?" in prompt
    assert "Conversation thread" in prompt or "You:" in prompt


def test_run_rag_agent_fast_mode():
    with patch("tempa.rag.graph.invoke_rag_fast_with_sources", return_value=("fast answer", [])) as fast:
        from tempa.rag.agent import run_rag_agent

        result = run_rag_agent("test query", mode="fast")
        assert result == "fast answer"
        fast.assert_called_once_with("test query")


def test_run_rag_agent_full_mode():
    with patch("tempa.rag.agent.invoke_rag_graph_with_sources") as full:
        full.return_value = {"answer": "full answer", "sources": []}
        from tempa.rag.agent import run_rag_agent

        result = run_rag_agent("test query", mode="full")
        assert result == "full answer"


def test_verifier_allows_mixed_calendar_success_and_failure():
    from tempa.router.verifier import verify_reply

    pack = {
        "action_facts": [
            "Created calendar event 'Tempa Testing' at Thu 17:10. Meet link: https://meet.google.com/abc-defg-hij",
            "Could not send calendar invite: No guest email found for Haroon Ali.",
        ],
        "conversation_thread": "",
        "memory_answer": "",
    }
    reply = (
        "I created Tempa Testing and Tempa is joining the Meet. "
        "I couldn't send the invite because I don't have Haroon's email."
    )
    ok, verified = verify_reply(reply, pack)
    assert ok is True or "Created calendar event" in verified


def test_groq_whisper_drops_silent_and_hallucinated_chunks():
    from tempa.meet.stt.groq_whisper import GroqWhisperAdapter

    adapter = GroqWhisperAdapter(sample_rate=16000, chunk_seconds=1.0, min_rms=80.0)
    assert adapter._is_hallucination("Thank you.")
    assert adapter._is_hallucination(".")
    assert not adapter._is_hallucination("Schedule the standup for tomorrow.")
    assert adapter._pcm_rms(b"\x00\x00" * 100) < 80.0


def test_action_state_prefers_most_recent_channel():
    from tempa.channels.whatsapp import action_state

    action_state._last_actions.clear()
    action_state.record_action("gmail", {"status": "sent"})
    action_state.record_action("calendar", {"status": "error", "error": "invite failed"})
    explanation = action_state.explain_last_action()
    assert explanation is not None
    assert "Calendar action failed" in explanation or "invite failed" in explanation
