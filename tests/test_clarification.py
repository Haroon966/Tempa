from tempa.agents.clarification import detect_missing_context


def test_detect_missing_email_recipient():
    q = detect_missing_context("send an email about the project update")
    assert q is not None
    assert "email" in q.lower()


def test_detect_missing_email_acknowledges_name_from_context():
    ctx = {"recent_user_messages": ["email Haroon about the launch"]}
    q = detect_missing_context("send the email", ctx)
    assert q is not None
    assert "Haroon" in q


def test_detect_missing_email_skips_when_recipient_present():
    assert detect_missing_context("send email to alice@example.com about the update") is None


def test_detect_missing_meet_link():
    q = detect_missing_context("join my meeting on Google Meet")
    assert q is not None
    assert "meet" in q.lower()


def test_detect_missing_meet_link_skips_with_url():
    url = "https://meet.google.com/abc-defg-hij"
    assert detect_missing_context(f"join {url}") is None


def test_detect_missing_repo_for_scan():
    q = detect_missing_context("scan repo for ci failures")
    assert q is not None
    assert "repository" in q.lower() or "github" in q.lower()


def test_detect_missing_repo_skips_with_github_url():
    text = "https://github.com/Haroon966/tempa scan this repo"
    assert detect_missing_context(text) is None


def test_detect_missing_jira_issue_key():
    assert detect_missing_context("list jira projects") is None

    assert detect_missing_context("get status of PROJ-99") is None

    q = detect_missing_context("show jira issue details for the login bug")
    assert q is not None
    assert "issue key" in q.lower() or "eng-" in q.lower() or "jira" in q.lower()


def test_detect_missing_calendar_time():
    q = detect_missing_context("schedule a meeting with the team about roadmap")
    assert q is not None
    assert "time" in q.lower() or "date" in q.lower()


def test_detect_skips_casual_greeting():
    assert detect_missing_context("hello") is None


def test_coordinator_asks_when_context_missing():
    import asyncio
    from unittest.mock import patch

    async def _run():
        with patch("tempa.agents.graph._should_use_varys", return_value=False):
            with patch("tempa.agents.graph._run_langgraph_coordinator_full") as lg:
                from tempa.agents.graph import run_coordinator_full

                result = await run_coordinator_full(
                    "send an email about the budget",
                    {"channel": "dashboard"},
                )
                lg.assert_not_called()
                return result

    result = asyncio.run(_run())
    assert "email" in result["response"].lower()
