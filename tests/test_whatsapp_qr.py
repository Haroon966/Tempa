import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from tempa.api.app import create_app
from tempa.channels.whatsapp import session as wa_session
from tempa.channels.whatsapp.session import clear_qr_code, get_qr_code
from tempa.channels.whatsapp.webhook import handle_webhook


@pytest.fixture(autouse=True)
def _reset_whatsapp_session_state(monkeypatch):
    wa_session._STATE_PATH = None
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield
    wa_session._STATE_PATH = None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_qrcode_webhook_stores_cached_image(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    clear_qr_code()

    await handle_webhook(
        {
            "event": "qrcode.updated",
            "instance": "tempa",
            "data": {
                "qrcode": {
                    "base64": "data:image/png;base64,abc123",
                    "code": "pairing-data",
                }
            },
        }
    )
    assert get_qr_code() == "data:image/png;base64,abc123"


def test_whatsapp_status_refresh_bypasses_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    state_dir = tmp_path / "sessions" / "whatsapp"
    state_dir.mkdir(parents=True)
    (state_dir / "connection_state.json").write_text(
        json.dumps(
            {
                "connected": False,
                "state": "close",
                "pause_auto_reply": True,
                "needs_qr_rescan": True,
                "qr_code": "data:image/png;base64,stale",
            }
        ),
        encoding="utf-8",
    )

    async def fake_resolved(self):
        return "close", False

    async def fake_sync():
        return {
            "connected": False,
            "state": "close",
            "pause_auto_reply": True,
            "needs_qr_rescan": True,
            "qr_code": "data:image/png;base64,stale",
        }

    async def fake_fetch_qr(refresh=False):
        assert refresh is True
        return {"status": "connecting", "qr_code": "data:image/png;base64,fresh", "pairing_code": None}

    async def fake_schedule_fetch_qr(*, refresh=False):
        assert refresh is True
        from tempa.channels.whatsapp.session import store_qr_code

        store_qr_code("data:image/png;base64,fresh")

    monkeypatch.setattr(
        "tempa.channels.whatsapp.client.EvolutionWhatsAppClient.resolved_connection_state",
        fake_resolved,
    )
    monkeypatch.setattr("tempa.api.app.sync_connection_from_evolution", fake_sync)
    monkeypatch.setattr("tempa.channels.whatsapp.qr_tasks.schedule_fetch_qr", fake_schedule_fetch_qr)

    app = create_app()
    client = TestClient(app)
    res = client.get("/api/connections/whatsapp?qr=1&refresh=1")
    assert res.status_code == 200
    assert res.json()["qr_code"] == "data:image/png;base64,fresh"


def test_whatsapp_status_returns_cached_qr_without_evolution(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    state_dir = tmp_path / "sessions" / "whatsapp"
    state_dir.mkdir(parents=True)
    (state_dir / "connection_state.json").write_text(
        json.dumps(
            {
                "connected": False,
                "state": "close",
                "pause_auto_reply": True,
                "needs_qr_rescan": True,
                "qr_code": "data:image/png;base64,cached",
            }
        ),
        encoding="utf-8",
    )

    async def fake_resolved(self):
        return "close", False

    async def fake_sync():
        return {
            "connected": False,
            "state": "close",
            "pause_auto_reply": True,
            "needs_qr_rescan": True,
            "qr_code": "data:image/png;base64,cached",
        }

    monkeypatch.setattr(
        "tempa.channels.whatsapp.client.EvolutionWhatsAppClient.resolved_connection_state",
        fake_resolved,
    )
    monkeypatch.setattr("tempa.api.app.sync_connection_from_evolution", fake_sync)

    app = create_app()
    client = TestClient(app)
    res = client.get("/api/connections/whatsapp?qr=1")
    assert res.status_code == 200
    assert res.json()["qr_code"] == "data:image/png;base64,cached"
