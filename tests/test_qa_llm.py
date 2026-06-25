"""Tests for QA LLM routing."""

import pytest

from tempa.qa.llm import deep_review_complete


@pytest.mark.asyncio
async def test_deep_review_uses_claude_when_configured(monkeypatch):
    async def fake_claude(**kwargs):
        return '[{"severity": "suggestion", "title": "ok", "body": "test"}]'

    monkeypatch.setattr("tempa.qa.claude.claude_complete", fake_claude)
    monkeypatch.setattr("tempa.qa.claude.claude_configured", lambda: True)

    text = await deep_review_complete("review this pr")
    assert "ok" in text


@pytest.mark.asyncio
async def test_deep_review_falls_back_to_groq(monkeypatch):
    async def fake_groq(messages, *, max_tokens=2048):
        return '{"findings": []}'

    monkeypatch.setattr("tempa.qa.llm.groq_complete", fake_groq)
    monkeypatch.setattr("tempa.qa.claude.claude_configured", lambda: False)

    text = await deep_review_complete("review this pr")
    assert "findings" in text
