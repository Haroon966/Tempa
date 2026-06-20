from __future__ import annotations

from tempa.rag.graph import invoke_rag_graph_with_sources


def run_rag_agent(query: str, *, mode: str = "full") -> str:
    answer, _sources = run_rag_agent_with_sources(query, mode=mode)
    return answer


def run_rag_agent_with_sources(query: str, *, mode: str = "full") -> tuple[str, list[dict]]:
    if mode == "fast":
        from tempa.rag.graph import invoke_rag_fast_with_sources

        return invoke_rag_fast_with_sources(query)
    result = invoke_rag_graph_with_sources(query)
    return result["answer"], result.get("sources", [])
