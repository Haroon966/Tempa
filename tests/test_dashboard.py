def test_dashboard_api(client):
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert "overall" in data
    assert "connections" in data
    assert "components" in data
    assert "flows" in data
    assert data["overall"]["total_components"] >= 10
