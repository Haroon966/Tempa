from __future__ import annotations

import os

import pytest

from tempa.pc.files import read_file, write_file
from tempa.pc.shell import run_shell
from tempa.settings import get_settings


def test_pc_shell_allowlist():
    result = run_shell("pwd")
    assert result["status"] == "success"
    blocked = run_shell("rm -rf /")
    assert blocked["status"] == "error"


def test_pc_files_roundtrip(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_dirs()
    target = settings.tempa_data_dir / "project_plan.md"
    write_result = write_file(str(target), "# Plan\n")
    assert write_result["status"] == "success"
    read_result = read_file(str(target))
    assert "Plan" in read_result["content"]
