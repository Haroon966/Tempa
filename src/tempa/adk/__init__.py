"""PARKED: Feature-flagged ADK coordinator spike (TEMPA_ADK_SPIKE).

Do not use in production. Shipping non-coding path is tools orchestrator or
TEMPA_COORDINATOR=hermes; coding remains Cursor. This module is retained only
for emergency experiments and will be removed once Hermes is proven.
"""

from __future__ import annotations

from tempa.adk.runner import run_adk_orchestrator

__all__ = ["run_adk_orchestrator"]
