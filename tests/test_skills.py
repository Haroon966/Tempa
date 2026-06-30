from __future__ import annotations

from tempa.skills import format_skills_for_prompt, load_all_skills, match_skills
from tempa.skills.loader import _parse_skill_file
from tempa.orchestrator.registry import filter_workers_for_context, orchestrator_manifest


def test_parse_skill_frontmatter(tmp_path):
    skill_path = tmp_path / "demo-skill" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_path.write_text(
        """---
name: demo-skill
description: Demo skill
triggers:
  - alpha
workers:
  - plugin
tools:
  - jira.search
priority: 5
---
# Demo

Do the thing.
""",
        encoding="utf-8",
    )
    skill = _parse_skill_file(skill_path)
    assert skill is not None
    assert skill.name == "demo-skill"
    assert "alpha" in skill.triggers
    assert skill.workers == ["plugin"]


def test_match_skills_jira():
    matched = match_skills("create jira ticket for login bug", {"channel": "slack"})
    names = {s.name for s in matched}
    assert "jira-tickets" in names


def test_guest_slack_excludes_gmail_skill_workers():
    matched = match_skills("What's in my inbox?", {"channel": "slack", "slack_privileged": False})
    workers = {w for s in matched for w in s.workers}
    allowed = filter_workers_for_context(workers, {"channel": "slack", "slack_privileged": False})
    assert "gmail" not in allowed


def test_format_skills_truncates():
    from tempa.skills.types import Skill

    long_body = "x" * 5000
    block = format_skills_for_prompt(
        [Skill(name="t", description="d", body=long_body, triggers=[], workers=[])]
    )
    assert len(block) < 5000


def test_orchestrator_manifest_includes_workers_and_skills():
    manifest = orchestrator_manifest()
    assert "orchestrator" in manifest
    assert len(manifest["workers"]) >= 5
    assert len(manifest["skills"]) >= 5


def test_load_bundled_skills():
    skills = load_all_skills()
    names = {s.name for s in skills}
    assert "jira-tickets" in names
    assert "slack-messaging" in names
    assert "gmail-calendar" in names
