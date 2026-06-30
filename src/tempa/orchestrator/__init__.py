"""Tempa orchestrator — centralized Master/Worker coordination."""

from tempa.orchestrator.config import load_orchestrator_config, allowed_workers_for_context

__all__ = ["load_orchestrator_config", "allowed_workers_for_context", "OrchestratorAgent", "run_orchestrator"]


def __getattr__(name: str):
    if name in ("OrchestratorAgent", "run_orchestrator"):
        from tempa.orchestrator.agent import OrchestratorAgent, run_orchestrator

        return OrchestratorAgent if name == "OrchestratorAgent" else run_orchestrator
    raise AttributeError(name)
