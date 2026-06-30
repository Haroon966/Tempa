from __future__ import annotations

from tempa.channels.jira.profiles import get_profile, save_profile


def test_profiles_file_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    save_profile(slack_user_id="U1", jira_account_id="x", display_name="Test")
    assert get_profile(slack_user_id="U1")["jira_account_id"] == "x"
    get_settings.cache_clear()
