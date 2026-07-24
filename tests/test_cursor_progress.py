"""Tempa Cursor Slack progress copy."""

from tempa.channels.slack.cursor_progress import msg_problem
from tempa.core.chat_errors import sanitize_user_error


def test_msg_problem_dubious_ownership_is_actionable():
    msg = msg_problem(
        "fatal: detected dubious ownership in repository at '/repos/compliancetracker'\n"
        "To add an exception for this directory, call:\n\n"
        "\tgit config --global --add safe.directory /repos/compliancetracker"
    )
    assert "ask again" in msg.lower()
    assert "fatal:" not in msg.lower()
    assert "git config" not in msg.lower()
    assert "dubious" not in msg.lower()


def test_msg_problem_timeout_suggests_retry():
    msg = msg_problem("TimeoutError")
    assert "too long" in msg.lower() or "retry" in msg.lower()
    assert "TimeoutError" not in msg


def test_msg_problem_never_leaks_raw_exception():
    msg = msg_problem("boom happened with /repos/compliancetracker and traceback")
    assert "boom happened" not in msg
    assert "traceback" not in msg.lower()
    assert "ask again" in msg.lower() or "something went wrong" in msg.lower()


def test_sanitize_keeps_technical_detail_out_of_slack():
    raw = "RuntimeError: gh pr create failed: HTTP 403 GraphQL: Resource not accessible"
    out = sanitize_user_error(raw)
    assert "GraphQL" not in out
    assert "403" not in out or "rate" in out.lower()
    assert len(out) < 200


def test_resolve_cloud_starting_ref_prefers_explicit(monkeypatch):
    from tempa.qa import cursor as cur

    assert cur.resolve_cloud_starting_ref("AliAhmed-004/gaming-adda", "develop") == "develop"
    assert cur._repo_slug("https://github.com/AliAhmed-004/gaming-adda.git") == "AliAhmed-004/gaming-adda"

    monkeypatch.setattr(
        "tempa.qa.github.auth.get_github_token",
        lambda repo=None: "tok",
    )
    monkeypatch.setattr(
        "tempa.qa.github.client.gh_get",
        lambda path, token: {"default_branch": "trunk"},
    )
    assert cur.resolve_cloud_starting_ref("AliAhmed-004/gaming-adda", None) == "trunk"

    monkeypatch.setattr(
        "tempa.qa.github.client.gh_get",
        lambda path, token: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert cur.resolve_cloud_starting_ref("AliAhmed-004/gaming-adda", None) == "main"


def test_ensure_repo_mirror_clones(tmp_path, monkeypatch):
    from tempa.channels.slack import cursor_worktree as wt
    from tempa.settings import get_settings

    monkeypatch.setenv("TEMPA_CURSOR_WORKTREE_ROOT", str(tmp_path / "wt"))
    get_settings.cache_clear()
    wt._GIT_SAFE_READY = False

    calls: list[list[str]] = []

    def fake_run(cmd, *, cwd=None):
        calls.append(list(cmd))
        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        # Pretend clone created a git dir
        if cmd[:2] == ["git", "clone"] or (len(cmd) > 3 and cmd[2] == "clone"):
            dest = Path(cmd[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / ".git").mkdir(exist_ok=True)
        return P()

    from pathlib import Path

    monkeypatch.setattr(wt, "_run", fake_run)
    monkeypatch.setattr(
        "tempa.qa.github.auth.get_github_token",
        lambda repo=None: "",
    )
    dest = wt.ensure_repo_mirror("AliAhmed-004/gaming-adda", ref="main")
    assert dest.exists()
    assert any("clone" in c for c in calls)
    get_settings.cache_clear()
