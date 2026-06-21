from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from tempa.settings import get_settings

from tempa.channels.whatsapp.session import parse_bridge_state

logger = logging.getLogger(__name__)

# Evolution manager UI uses 30s; create waits up to 5s after connect internally.
_CONNECT_TIMEOUT = 55.0
_CONNECT_TRIGGER_TIMEOUT = 55.0
_CONNECT_QR_TIMEOUT = 55.0
_CREATE_TIMEOUT = 90.0
_CONNECT_COOLDOWN_SECONDS = 90.0
_last_connect_trigger: float = 0.0
_WEBHOOK_QR_WAIT_SECONDS = 45

_WEBHOOK_EVENTS = ["MESSAGES_UPSERT", "CONNECTION_UPDATE", "QRCODE_UPDATED"]


class WhatsAppBridgeClient:
    """REST client for the in-repo WhatsApp bridge sidecar."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.evolution_api_url.rstrip("/")
        self.api_key = settings.evolution_api_key
        self.instance = settings.tempa_instance_name

    def _headers(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    def _default_webhook_url(self) -> str:
        settings = get_settings()
        base = settings.tempa_webhook_base_url.strip() or (
            f"http://127.0.0.1:{settings.tempa_daemon_port}"
        )
        return f"{base.rstrip('/')}/webhooks/whatsapp"

    def _webhook_payload(self, webhook_url: str) -> dict[str, Any]:
        return {
            "enabled": True,
            "url": webhook_url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": _WEBHOOK_EVENTS,
        }

    async def _instance_row(self) -> dict[str, Any] | None:
        for inst in await self.fetch_instances():
            name = inst.get("name") or inst.get("instanceName")
            if name == self.instance:
                return inst
        return None

    async def _has_linked_device(self) -> bool:
        inst = await self._instance_row()
        return bool(inst and inst.get("ownerJid"))

    async def ensure_webhook(self, webhook_url: str | None = None, *, enabled: bool = True) -> None:
        """Register daemon webhook on the bridge (required for CONNECTION_UPDATE / QRCODE_UPDATED)."""
        from tempa.debug_agent_log import agent_log

        url = webhook_url or self._default_webhook_url()
        try:
            await self.set_webhook(url, enabled=enabled)
            # #region agent log
            agent_log(
                location="client.py:ensure_webhook",
                message="webhook registered",
                data={"url": url, "enabled": enabled},
                hypothesis_id="H2",
            )
            # #endregion
        except Exception as exc:
            logger.warning("Webhook registration failed: %s", exc)

    async def ensure_instance(self, webhook_url: str | None = None) -> None:
        """Create bridge instance if missing; always ensure webhook is registered."""
        if await self._instance_row() is not None:
            if webhook_url:
                await self.ensure_webhook(webhook_url, enabled=True)
            return
        try:
            state_name, _ = parse_bridge_state(await self.connection_state())
            if state_name not in {"", "unknown", "disconnected"}:
                return
        except Exception:
            pass
        try:
            await self.create_instance(webhook_url=webhook_url)
        except RuntimeError as exc:
            if "already in use" in str(exc).lower():
                logger.info("Evolution instance already registered — continuing")
                return
            raise

    @staticmethod
    def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
        try:
            body = exc.response.json()
            messages = body.get("response", {}).get("message", body.get("message"))
            if isinstance(messages, list):
                return "; ".join(str(m) for m in messages)
            if isinstance(messages, str):
                return messages
            if isinstance(body.get("error"), str):
                return body["error"]
        except Exception:
            pass
        return str(exc)

    async def create_instance(self, *, webhook_url: str | None = None) -> dict[str, Any]:
        """Vendor createInstance: optional qrcode connect + 5s wait, returns qrcode in body."""
        from tempa.channels.whatsapp.session import store_qr_code

        payload: dict[str, Any] = {
            "instanceName": self.instance,
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": False,
        }
        async with httpx.AsyncClient(timeout=_CREATE_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/instance/create",
                json=payload,
                headers=self._headers(),
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(self._http_error_detail(exc)) from exc
            data = resp.json()
            qr_block = data.get("qrcode") or data.get("qrCode") or data
            base64_qr = await asyncio.to_thread(self._extract_qr_from_connect, qr_block)
            if base64_qr:
                store_qr_code(base64_qr)
            return data

    async def _connect_once_for_qr(self, *, force: bool = False) -> dict[str, Any] | None:
        """Single Evolution connect — concurrent calls prevent QR delivery."""
        import time

        from tempa.debug_agent_log import agent_log

        global _last_connect_trigger
        now = time.monotonic()
        if not force and now - _last_connect_trigger < _CONNECT_COOLDOWN_SECONDS:
            # #region agent log
            agent_log(
                location="client.py:_connect_once_for_qr:skip",
                message="connect cooldown active",
                data={"age_s": round(now - _last_connect_trigger, 1)},
                hypothesis_id="H15",
                run_id="post-fix",
            )
            # #endregion
            return None
        _last_connect_trigger = now
        url = f"{self.base_url}/instance/connect/{self.instance}"
        try:
            async with httpx.AsyncClient(timeout=_CONNECT_QR_TIMEOUT) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                if resp.content:
                    data = resp.json()
                    if isinstance(data, dict) and not data.get("error"):
                        # #region agent log
                        agent_log(
                            location="client.py:_connect_once_for_qr:ok",
                            message="connect returned",
                            data={
                                "keys": list(data.keys()),
                                "base64_len": len(data.get("base64") or ""),
                                "count": data.get("count"),
                            },
                            hypothesis_id="H15",
                            run_id="post-fix",
                        )
                        # #endregion
                        return data
        except httpx.TimeoutException:
            logger.info("Evolution connect in progress — waiting for pairing state")
        except httpx.HTTPError as exc:
            logger.warning("Evolution connect failed: %s", exc)
        return None

    async def trigger_connect(self, *, for_qr: bool = True) -> dict[str, Any] | None:
        """Start Evolution pairing without blocking on webhook retries (short HTTP timeout)."""
        from tempa.channels.whatsapp.numbers import get_owner_whatsapp_number

        url = f"{self.base_url}/instance/connect/{self.instance}"
        if not for_qr:
            number = get_owner_whatsapp_number()
            if number:
                url = f"{url}?number={number}"
        try:
            async with httpx.AsyncClient(timeout=_CONNECT_TRIGGER_TIMEOUT) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                if resp.content:
                    data = resp.json()
                    if isinstance(data, dict) and not data.get("error"):
                        return data
        except httpx.TimeoutException:
            logger.info("Evolution connect triggered — waiting for QR via webhook")
        except httpx.HTTPError as exc:
            logger.warning("Evolution connect trigger failed: %s", exc)
        return None

    async def connect(self, *, for_qr: bool | None = None) -> dict[str, Any]:
        """
        Vendor connectToWhatsapp:
        - open → connection state
        - connecting → cached qrCode (safe to call while pairing)
        - close → start connect, wait ~2s, return qrCode
        """
        from tempa.channels.whatsapp.numbers import get_owner_whatsapp_number

        if for_qr is None:
            for_qr = not await self._has_linked_device()

        url = f"{self.base_url}/instance/connect/{self.instance}"
        if not for_qr:
            number = get_owner_whatsapp_number()
            if number:
                url = f"{url}?number={number}"
        async with httpx.AsyncClient(timeout=_CONNECT_TIMEOUT) as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 404:
                await self.create_instance()
                resp = await client.get(url, headers=self._headers())
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(self._http_error_detail(exc)) from exc
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(str(data.get("message") or data.get("error")))
            return data

    async def bridge_restart(self) -> dict[str, Any]:
        """Restart bridge instance: reconnect websocket (no delete/recreate)."""
        async with httpx.AsyncClient(timeout=_CONNECT_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/instance/restart/{self.instance}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return {"status": "not_found"}
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = self._http_error_detail(exc)
                logger.warning("Evolution restart: %s", detail)
                return {"status": "error", "detail": detail}
            if resp.content:
                return resp.json()
            return {"status": "restarted"}

    async def connection_state(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/instance/connectionState/{self.instance}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return {"state": "disconnected"}
            resp.raise_for_status()
            return resp.json()

    async def fetch_instances(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/instance/fetchInstances",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

    async def resolved_connection_state(self) -> tuple[str, bool]:
        """Prefer live connectionState; fetchInstances can lag during pairing."""
        from tempa.debug_agent_log import agent_log

        inst = await self._instance_row()
        if inst and inst.get("ownerJid"):
            return "open", True

        live_raw = await self.connection_state()
        live_name, live_connected = parse_bridge_state(live_raw)
        db_status = ""
        if inst:
            db_status = str(inst.get("connectionStatus") or inst.get("state") or "").lower()
            if db_status in {"open", "connected"}:
                return "open", True

        if live_connected:
            return "open", True
        if live_name and live_name.lower() not in {"", "unknown"}:
            # #region agent log
            agent_log(
                location="client.py:resolved_connection_state",
                message="using live connectionState",
                data={"live_name": live_name, "db_status": db_status},
                hypothesis_id="H6",
            )
            # #endregion
            return live_name, False

        if db_status:
            return db_status, False
        return live_name or "disconnected", False

    async def logout(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{self.base_url}/instance/logout/{self.instance}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return {"status": "disconnected"}
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {"status": "disconnected"}

    async def delete_instance(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{self.base_url}/instance/delete/{self.instance}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return {"status": "deleted"}
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return {"status": "deleted"}

    async def restart_instance(self, webhook_url: str) -> dict[str, Any]:
        """
        Vendor-aligned recovery: set webhook, optional restart (if open/connecting), then connect for QR.
        Never delete/recreate — that breaks pairing and causes LOGOUT/REMOVED.
        """
        from tempa.channels.whatsapp.session import clear_qr_code, mark_disconnected, update_connection_state

        await self.ensure_instance(webhook_url=webhook_url)
        state_name, connected = await self.resolved_connection_state()
        if connected:
            try:
                await self.set_webhook(webhook_url)
            except Exception as exc:
                logger.warning("Webhook registration failed: %s", exc)

        state_name, connected = await self.resolved_connection_state()
        clear_qr_code()

        if connected:
            update_connection_state("open")
            return {"status": "open", "qr_code": None, "pairing_code": None}

        # Never restart while pairing — vendor returns cached QR for connecting.
        if state_name == "open":
            await self.bridge_restart()

        qr_data = await self.fetch_qr(refresh=True)
        if not qr_data.get("qr_code"):
            mark_disconnected()
        return qr_data

    @staticmethod
    def _qr_image_from_code(code: str) -> str:
        import base64
        import io

        import qrcode

        img = qrcode.make(code)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    @staticmethod
    def _normalize_qr_base64(base64_qr: str) -> str:
        if base64_qr.startswith("data:"):
            return base64_qr
        return f"data:image/png;base64,{base64_qr}"

    @staticmethod
    def _extract_qr_from_connect(data: dict[str, Any]) -> str | None:
        """Parse vendor qrCode: {pairingCode, code, base64, count} or nested qrcode key."""
        if not data:
            return None

        base64_qr = data.get("base64")
        if isinstance(base64_qr, str) and base64_qr:
            return WhatsAppBridgeClient._normalize_qr_base64(base64_qr)

        for key in ("qrcode", "qrCode"):
            qrcode = data.get(key)
            if isinstance(qrcode, dict):
                nested = qrcode.get("base64")
                if isinstance(nested, str) and nested:
                    return WhatsAppBridgeClient._normalize_qr_base64(nested)
                code = qrcode.get("code")
                if isinstance(code, str) and code:
                    return WhatsAppBridgeClient._qr_image_from_code(code)
            elif isinstance(qrcode, str) and qrcode:
                return WhatsAppBridgeClient._qr_image_from_code(qrcode)

        code = data.get("code")
        if isinstance(code, str) and code:
            return WhatsAppBridgeClient._qr_image_from_code(code)
        return None

    @staticmethod
    def _extract_pairing_code(data: dict[str, Any]) -> str | None:
        pairing = data.get("pairingCode")
        if isinstance(pairing, str) and pairing:
            return pairing
        for key in ("qrcode", "qrCode"):
            qrcode = data.get(key)
            if isinstance(qrcode, dict):
                nested = qrcode.get("pairingCode")
                if isinstance(nested, str) and nested:
                    return nested
        return None

    async def fetch_qr(self, *, refresh: bool = False) -> dict[str, Any]:
        """
        Vendor-aligned QR fetch: GET /instance/connect once, then brief webhook wait.
        """
        global _last_connect_trigger
        from tempa.channels.whatsapp.session import clear_qr_code, get_qr_code, store_qr_code

        if refresh:
            clear_qr_code()
            _last_connect_trigger = 0.0
        else:
            cached = get_qr_code()
            state_name, connected = await self.resolved_connection_state()
            if connected:
                return {"status": "open", "qr_code": None, "pairing_code": None}
            if cached and state_name == "connecting":
                return {"status": "connecting", "qr_code": cached, "pairing_code": None}

        state_name, connected = await self.resolved_connection_state()
        if connected:
            return {"status": "open", "qr_code": None, "pairing_code": None}

        synced = await self.read_cached_qr()
        if synced:
            return {"status": "connecting", "qr_code": synced, "pairing_code": None}

        webhook_url = self._default_webhook_url()
        await self.ensure_webhook(webhook_url, enabled=True)

        if refresh and state_name in {"close", "disconnected", "refused"}:
            logger.info("WhatsApp refresh — recreating Evolution instance")
            try:
                await self.delete_instance()
                await asyncio.sleep(2)
            except Exception as exc:
                logger.warning("Instance delete failed: %s", exc)
            try:
                await self.create_instance()
            except RuntimeError as exc:
                if "already in use" not in str(exc).lower():
                    logger.warning("Instance recreate failed: %s", exc)
            _last_connect_trigger = 0.0
            await asyncio.sleep(5)
            polled = await self.poll_connect_qr(attempts=30, interval=3.0, force_connect=True)
            base64_qr = polled.get("qr_code")
            if base64_qr:
                return polled
        else:
            polled = await self.poll_connect_qr(force_connect=refresh)
            base64_qr = polled.get("qr_code")
            if base64_qr:
                return polled

        state_name, connected = await self.resolved_connection_state()
        base64_qr = polled.get("qr_code") or get_qr_code()
        if base64_qr:
            store_qr_code(base64_qr)

        status = state_name if state_name not in {"", "close", "unknown"} else "connecting"
        # #region agent log
        from tempa.debug_agent_log import agent_log

        agent_log(
            location="client.py:fetch_qr:exit",
            message="fetch_qr done",
            data={
                "refresh": refresh,
                "state_name": state_name,
                "connected": connected,
                "qr_len": len(base64_qr or ""),
            },
            hypothesis_id="H3",
            run_id="post-fix",
        )
        # #endregion
        return {
            "status": status,
            "qr_code": base64_qr,
            "pairing_code": polled.get("pairing_code"),
        }

    async def send_text(self, number: str, text: str) -> dict[str, Any]:
        payload = {"number": number, "text": text}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/message/sendText/{self.instance}",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def mark_messages_as_read(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Send read receipts so the sender sees messages as viewed (blue ticks)."""
        key = raw_item.get("key") if isinstance(raw_item, dict) else None
        if not isinstance(key, dict):
            return {"read": "skipped", "reason": "missing key"}
        remote_jid = str(key.get("remoteJid") or "")
        message_id = str(key.get("id") or "")
        if not remote_jid or not message_id or key.get("fromMe"):
            return {"read": "skipped", "reason": "invalid key"}
        payload: dict[str, Any] = {
            "readMessages": [
                {
                    "remoteJid": remote_jid,
                    "id": message_id,
                    "fromMe": bool(key.get("fromMe")),
                }
            ]
        }
        participant = key.get("participant")
        if isinstance(participant, str) and participant:
            payload["readMessages"][0]["participant"] = participant
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/chat/markMessageAsRead/{self.instance}",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def send_media(
        self,
        number: str,
        file_path: str,
        *,
        caption: str = "",
        mediatype: str = "document",
    ) -> dict[str, Any]:
        import base64
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "reason": "File not found"}
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {
            "number": number,
            "mediatype": mediatype,
            "media": data,
            "fileName": path.name,
            "caption": caption,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/message/sendMedia/{self.instance}",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def set_webhook(self, webhook_url: str, *, enabled: bool = True) -> dict[str, Any]:
        payload = {"webhook": {**self._webhook_payload(webhook_url), "enabled": enabled}}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/webhook/set/{self.instance}",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def _read_qr_endpoint(self) -> dict[str, Any] | None:
        """Read-only QR poll — does not start a new pairing session."""
        url = f"{self.base_url}/instance/qr/{self.instance}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 404 or not resp.content:
                    return None
                return resp.json()
        except httpx.HTTPError:
            return None

    async def read_cached_qr(self) -> str | None:
        """Prefer live bridge QR over local cache — avoids serving expired codes after Baileys rotation."""
        from tempa.channels.whatsapp.session import get_qr_code, store_qr_code
        from tempa.debug_agent_log import agent_log

        state_name, connected = await self.resolved_connection_state()
        if connected:
            return None

        local_cached = get_qr_code()
        data = await self._read_qr_endpoint()
        if data:
            base64_qr = await asyncio.to_thread(self._extract_qr_from_connect, data)
            bridge_count = data.get("count")
            if base64_qr:
                store_qr_code(base64_qr)
                # #region agent log
                agent_log(
                    location="client.py:read_cached_qr:ok",
                    message="synced QR from bridge cache",
                    data={
                        "qr_len": len(base64_qr),
                        "count": bridge_count,
                        "had_local": bool(local_cached),
                        "state_name": state_name,
                    },
                    hypothesis_id="H1",
                )
                # #endregion
                return base64_qr
            if bridge_count and local_cached:
                from tempa.channels.whatsapp.session import clear_qr_code

                clear_qr_code()
                # #region agent log
                agent_log(
                    location="client.py:read_cached_qr:stale",
                    message="cleared stale local QR — bridge has no active code",
                    data={"count": bridge_count, "state_name": state_name},
                    hypothesis_id="H1",
                )
                # #endregion
            elif not data.get("base64") and not data.get("code") and local_cached:
                from tempa.channels.whatsapp.session import clear_qr_code

                clear_qr_code()
                local_cached = None
                # #region agent log
                agent_log(
                    location="client.py:read_cached_qr:dead_socket",
                    message="cleared local QR — bridge socket not pairing",
                    data={"state_name": state_name},
                    hypothesis_id="H3",
                )
                # #endregion

        if local_cached and state_name == "connecting":
            return local_cached

        if state_name != "connecting":
            return local_cached
        url = f"{self.base_url}/instance/connect/{self.instance}"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 404 or not resp.content:
                    return None
                data = resp.json()
                base64_qr = await asyncio.to_thread(self._extract_qr_from_connect, data)
                if base64_qr:
                    store_qr_code(base64_qr)
                    return base64_qr
        except httpx.HTTPError as exc:
            logger.debug("Bridge read_cached_qr failed: %s", exc)
        return None

    async def poll_connect_qr(
        self,
        *,
        attempts: int = 40,
        interval: float = 2.0,
        force_connect: bool = False,
    ) -> dict[str, Any]:
        """Trigger pairing once, then poll connect until Evolution returns QR."""
        from tempa.channels.whatsapp.session import get_qr_code, store_qr_code
        from tempa.debug_agent_log import agent_log

        url = f"{self.base_url}/instance/connect/{self.instance}"
        last_data: dict[str, Any] = {}
        pairing_started = False

        for attempt in range(attempts):
            cached = get_qr_code()
            if cached:
                return {"status": "connecting", "qr_code": cached, "pairing_code": None}

            state_name, connected = await self.resolved_connection_state()
            if connected:
                return {"status": "open", "qr_code": None, "pairing_code": None}

            if state_name == "connecting":
                pairing_started = True

            if (
                not pairing_started
                and state_name in {"close", "disconnected", "refused", "unknown", ""}
            ):
                pairing_started = True
                await self.trigger_connect(for_qr=True)
                # #region agent log
                agent_log(
                    location="client.py:poll_connect_qr:trigger",
                    message="pairing triggered",
                    data={"attempt": attempt + 1, "state_name": state_name, "force": force_connect},
                    hypothesis_id="H18",
                    run_id="post-fix",
                )
                # #endregion
                await asyncio.sleep(3)
                continue

            if pairing_started:
                data = await self._read_qr_endpoint()
                if data:
                    last_data = data
                    base64_qr = await asyncio.to_thread(self._extract_qr_from_connect, data)
                    if base64_qr:
                        store_qr_code(base64_qr)
                        return {
                            "status": "connecting",
                            "qr_code": base64_qr,
                            "pairing_code": self._extract_pairing_code(data),
                        }
                try:
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        resp = await client.get(url, headers=self._headers())
                        if resp.status_code == 404:
                            break
                        resp.raise_for_status()
                        if resp.content:
                            last_data = resp.json()
                            # #region agent log
                            agent_log(
                                location="client.py:poll_connect_qr:read",
                                message="connect read while pairing",
                                data={
                                    "attempt": attempt + 1,
                                    "state_name": state_name,
                                    "keys": list(last_data.keys()),
                                    "code_len": len(last_data.get("code") or ""),
                                    "base64_len": len(last_data.get("base64") or ""),
                                    "count": last_data.get("count"),
                                },
                                hypothesis_id="H18",
                                run_id="post-fix",
                            )
                            # #endregion
                            base64_qr = await asyncio.to_thread(
                                self._extract_qr_from_connect, last_data
                            )
                            if base64_qr:
                                store_qr_code(base64_qr)
                                return {
                                    "status": "connecting",
                                    "qr_code": base64_qr,
                                    "pairing_code": self._extract_pairing_code(last_data),
                                }
                except httpx.TimeoutException:
                    logger.debug("Evolution connect read %s timed out", attempt + 1)
                except httpx.HTTPError as exc:
                    logger.warning("Evolution connect read failed: %s", exc)

            await asyncio.sleep(interval)

        # #region agent log
        agent_log(
            location="client.py:poll_connect_qr:exit",
            message="poll finished without qr",
            data={
                "attempts": attempts,
                "pairing_started": pairing_started,
                "last_keys": list(last_data.keys()) if last_data else [],
            },
            hypothesis_id="H4",
            run_id="post-fix",
        )
        # #endregion
        return {
            "status": "connecting",
            "qr_code": None,
            "pairing_code": self._extract_pairing_code(last_data),
        }

    async def startup_sync(self, webhook_url: str) -> None:
        """Ensure instance exists; enable webhooks only when already connected."""
        from tempa.channels.whatsapp.session import update_connection_state

        await self.ensure_instance(webhook_url=webhook_url)
        state_name, connected = await self.resolved_connection_state()
        if connected:
            try:
                await self.set_webhook(webhook_url)
            except Exception:
                pass
            from tempa.channels.whatsapp.numbers import sync_linked_owner_from_bridge

            await sync_linked_owner_from_bridge()
            update_connection_state("open")
            return
        await self.ensure_webhook(webhook_url, enabled=True)
        if state_name == "close" and await self._has_linked_device():
            try:
                await self.connect(for_qr=False)
                state_name, connected = await self.resolved_connection_state()
                update_connection_state("open" if connected else state_name)
            except Exception:
                pass
