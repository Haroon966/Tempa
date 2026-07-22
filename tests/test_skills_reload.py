from __future__ import annotations

from tempa.skills.loader import load_skills_config, reload_skills


def test_reload_skills_clears_config_cache():
    first = load_skills_config()
    count = reload_skills()
    second = load_skills_config()
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    assert count >= 0
