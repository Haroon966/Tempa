import json

from fastapi.testclient import TestClient

from tempa.api.app import create_app
from tempa.channels.whatsapp import session as wa_session


def test_whatsapp_allowed_numbers_api(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WHATSAPP_OWNER_NUMBER", "03435971748")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    wa_session._STATE_PATH = None

    app = create_app()
    client = TestClient(app)

    res = client.put(
        "/api/connections/whatsapp/allowed-numbers",
        json={"additional_numbers": ["03001234567", "03435971748", ""]},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["primary_number"] == "923435971748"
    assert data["additional_numbers"] == ["923001234567"]
    assert "923435971748" in data["allowed_numbers"]
    assert "923001234567" in data["allowed_numbers"]

    stored = json.loads(
        (tmp_path / "sessions" / "whatsapp" / "allowed_reply_numbers.json").read_text(encoding="utf-8")
    )
    assert stored["additional"] == ["923001234567"]

    get_settings.cache_clear()
