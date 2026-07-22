"""Hermes Agent integration for Tempa's non-coding tools coordinator.

Install optional: pip install 'tempa[hermes]' (or hermes-agent from NousResearch).
Enable with TEMPA_COORDINATOR=hermes. Slack coding still short-circuits to Cursor.
"""

from __future__ import annotations

from tempa.hermes.coordinator import hermes_available, run_hermes_coordinator

__all__ = ["hermes_available", "run_hermes_coordinator"]
