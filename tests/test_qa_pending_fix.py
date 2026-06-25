"""Tests for QA autofix pending action."""

import pytest

from tempa.core.pending_actions import create_pending_action


@pytest.mark.asyncio
async def test_qa_autofix_pending_type():
    action = create_pending_action(
        "qa_autofix",
        {
            "repo": "org/r",
            "branch": "main",
            "file": "src/foo.py",
            "finding_id": "fid-1",
            "title": "Fix lint",
            "patch_content": "x = 1\n",
        },
        risk_level="high",
    )
    assert action["type"] == "qa_autofix"
    assert action["risk_level"] == "high"
    assert "Fix lint" in action["title"]
