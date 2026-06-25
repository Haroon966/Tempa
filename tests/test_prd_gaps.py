def test_groq_models_api(client):
    res = client.get("/api/connections/groq/models")
    assert res.status_code == 200
    data = res.json()
    assert "chains" in data
    assert "reasoning" in data["chains"]


def test_plugins_api(client):
    res = client.get("/api/plugins")
    assert res.status_code == 200
    tools = res.json().get("tools", [])
    assert any(t["name"] == "pc.run_shell" for t in tools)


def test_connections_expected_keys(client):
    res = client.get("/api/connections")
    data = res.json()
    assert {"daemon", "groq", "google", "gmail", "whatsapp", "rag"}.issubset(data.keys())
    assert "email" not in data


def test_gmail_disconnect(client):
    res = client.delete("/api/connections/gmail")
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is False
    assert data["status"] == "disconnected"
    gmail = client.get("/api/connections").json()["gmail"]
    assert gmail["connected"] is False


def test_gmail_connect_requires_credentials(client, monkeypatch):
    monkeypatch.setattr(
        "tempa.api.app.google_credentials_configured",
        lambda: False,
    )
    res = client.post("/api/connections/gmail")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert "credentials" in data["detail"].lower()


def test_google_credentials_save(client):
    res = client.post(
        "/api/connections/google/credentials",
        json={"client_id": "test-client.apps.googleusercontent.com", "client_secret": "test-secret"},
    )
    assert res.status_code == 200
    assert res.json()["credentials_configured"] is True
    google = client.get("/api/connections").json()["google"]
    assert google["credentials_configured"] is True


def test_google_disconnect(client):
    res = client.delete("/api/connections/google")
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is False
    assert data["status"] == "disconnected"


def test_whatsapp_status_no_auto_qr(client, monkeypatch):
    async def fake_resolved(self):
        return "close", False

    monkeypatch.setattr(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.resolved_connection_state",
        fake_resolved,
    )

    res = client.get("/api/connections/whatsapp")
    assert res.status_code == 200
    data = res.json()
    assert data["qr_code"] is None
    assert data["connected"] is False


def test_whatsapp_connect_and_disconnect(client, monkeypatch):
    calls = {"logout": 0}

    async def fake_schedule_fetch_qr(*_args, **_kwargs):
        from tempa.channels.whatsapp.session import store_qr_code

        store_qr_code("data:image/png;base64," + ("a" * 500))

    async def fake_resolved(self):
        return "connecting", False

    async def fake_logout(self):
        calls["logout"] += 1
        return {"status": "disconnected"}

    monkeypatch.setattr("tempa.channels.whatsapp.qr_tasks.schedule_fetch_qr", fake_schedule_fetch_qr)
    monkeypatch.setattr(
        "tempa.api.app.schedule_fetch_qr",
        fake_schedule_fetch_qr,
        raising=False,
    )
    monkeypatch.setattr(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.resolved_connection_state",
        fake_resolved,
    )
    monkeypatch.setattr("tempa.api.app.WhatsAppBridgeClient.logout", fake_logout)

    connect = client.post("/api/connections/whatsapp/connect")
    assert connect.status_code == 200
    assert connect.json()["qr_code"] is not None

    disconnect = client.delete("/api/connections/whatsapp")
    assert disconnect.status_code == 200
    assert disconnect.json()["connected"] is False
    assert calls["logout"] == 1
