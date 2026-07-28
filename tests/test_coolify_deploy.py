"""Self-check for Coolify intent + request shaping (no live Coolify required)."""

from __future__ import annotations

from tempa.channels.coolify.client import (
    normalize_git_repository,
    parse_env_block,
    looks_like_env_only,
)
from tempa.channels.coolify.intent import (
    is_deploy_confirm,
    parse_deploy_request,
    wants_coolify_deploy,
)
from tempa.orchestrator.routing import is_coding_work_request


def test_wants_coolify_deploy_detects_verbs():
    assert wants_coolify_deploy("deploy https://github.com/acme/widgets")
    assert wants_coolify_deploy("redeploy acme/widgets on coolify")
    assert wants_coolify_deploy("put this live on coolify")
    assert not wants_coolify_deploy("improve https://github.com/acme/widgets")


def test_deploy_not_coding_work():
    assert is_coding_work_request("fix oauth in https://github.com/org/tempa") is True
    assert is_coding_work_request("deploy https://github.com/org/tempa") is False
    assert is_coding_work_request("redeploy org/tempa on coolify") is False


def test_parse_deploy_request_fields():
    req = parse_deploy_request(
        "deploy https://github.com/acme/widgets branch develop port 8080\nAPI_KEY=secret\nDEBUG=1"
    )
    assert req.git_repository == "acme/widgets"
    assert req.git_branch == "develop"
    assert req.ports_exposes == "8080"
    assert req.envs.get("API_KEY") == "secret"
    assert req.envs.get("DEBUG") == "1"


def test_normalize_and_env_helpers():
    assert normalize_git_repository("https://github.com/Acme/Widget.git") == "Acme/Widget"
    assert normalize_git_repository("git@github.com:Acme/Widget.git") == "Acme/Widget"
    from tempa.channels.coolify.client import git_repository_url

    assert git_repository_url("Acme/Widget") == "https://github.com/Acme/Widget"
    assert git_repository_url("Acme/Widget", ssh=True) == "git@github.com:Acme/Widget.git"
    envs = parse_env_block("# comment\nFOO=bar\nBAZ=qux\nnot an env\n")
    assert envs == {"FOO": "bar", "BAZ": "qux"}
    assert looks_like_env_only("FOO=1\nBAR=2\n")
    assert is_deploy_confirm("yes")
    assert is_deploy_confirm("ship it")


if __name__ == "__main__":
    test_wants_coolify_deploy_detects_verbs()
    test_deploy_not_coding_work()
    test_parse_deploy_request_fields()
    test_normalize_and_env_helpers()
    print("coolify self-check ok")
