"""Tests for local QA checks."""

from pathlib import Path

from tempa.qa.checks.local import parse_ruff_findings, run_ruff


def test_parse_ruff_findings():
    output = "src/foo.py:10:1: E501 line too long\n"
    items = parse_ruff_findings(output)
    assert len(items) == 1
    assert items[0]["file"] == "src/foo.py"
    assert items[0]["line"] == 10


def test_run_ruff_skipped_when_no_paths(tmp_path: Path):
    result = run_ruff(tmp_path)
    assert result.status == "skipped"
