def test_dashboard_api(client):
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert "overall" in data
    assert "connections" in data
    assert "components" in data
    assert "flows" in data
    assert data["overall"]["total_components"] >= 10


def test_meetings_readiness_endpoint(client):
    res = client.get("/api/meetings/readiness")
    assert res.status_code == 200
    data = res.json()
    assert "ready" in data
    assert "consent" in data


def test_meetings_active_endpoint(client):
    res = client.get("/api/meetings/active")
    assert res.status_code == 200
    data = res.json()
    assert "active" in data
    assert isinstance(data["active"], list)


def test_dashboard_spa_routes(client):
    from tempa.settings import get_settings

    settings = get_settings()
    if not (settings.project_root / "dashboard" / "dist" / "index.html").exists():
        return

    for path in ("/overview", "/agent", "/mail", "/qa", "/dashboard"):
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "<div id=\"root\">" in res.text
