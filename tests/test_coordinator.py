def test_coordinator_graph_has_rag_gate():
    from tempa.agents.graph import build_coordinator_graph

    graph = build_coordinator_graph()
    nodes = set(graph.get_graph().nodes.keys())
    assert "rag_gate" in nodes
    assert "plan" in nodes
    assert "execute_waves" in nodes
    assert "plan_preview" in nodes
    assert "channel_followup" in nodes


def test_compute_execution_waves_respects_depends_on():
    from tempa.agents.graph import compute_execution_waves

    subtasks = [
        {"agent": "calendar", "task": "find meet link", "depends_on": []},
        {"agent": "meet", "task": "join meet", "depends_on": ["calendar"]},
        {"agent": "channel", "task": "notify team", "depends_on": ["meet"]},
    ]
    waves = compute_execution_waves(subtasks)
    assert len(waves) == 3
    assert waves[0][0]["agent"] == "calendar"
    assert waves[1][0]["agent"] == "meet"
    assert waves[2][0]["agent"] == "channel"
