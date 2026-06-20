from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web

from tempa.pc.transfer.pairing import consume_token, _load_transfer_config

logger = logging.getLogger(__name__)

_server_task: asyncio.Task | None = None
_runner: web.AppRunner | None = None


async def _handle_download(request: web.Request) -> web.StreamResponse:
    token = request.match_info.get("token", "")
    record = consume_token(token)
    if not record:
        return web.Response(status=404, text="Transfer link expired or invalid")

    path = Path(record["path"])
    if not path.exists():
        return web.Response(status=404, text="File no longer available")

    resp = web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})
    return resp


async def _handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "tempa-transfer"})


def _build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/download/{token}", _handle_download)
    app.router.add_get("/health", _handle_health)
    return app


async def ensure_transfer_server() -> None:
    global _server_task, _runner
    cfg = _load_transfer_config()
    if not cfg.get("enabled", True):
        return
    if _runner is not None:
        return

    port = int(cfg.get("port", 8788))
    host = str(cfg.get("bind_host", "0.0.0.0"))
    app = _build_app()
    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, host, port)
    await site.start()
    logger.info("Tempa transfer server listening on %s:%s", host, port)

    try:
        from tempa.pc.transfer.discovery import register_service

        register_service(port)
    except Exception as exc:
        logger.debug("mDNS registration skipped: %s", exc)


async def stop_transfer_server() -> None:
    global _runner
    if _runner:
        await _runner.cleanup()
        _runner = None
