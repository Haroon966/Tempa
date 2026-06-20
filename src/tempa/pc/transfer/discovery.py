from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)

_service = None


def register_service(port: int) -> None:
    global _service
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        return

    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    info = ServiceInfo(
        "_tempa-transfer._tcp.local.",
        f"Tempa Transfer on {hostname}._tempa-transfer._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties={"path": "/download"},
    )
    _service = Zeroconf()
    _service.register_service(info)
    logger.info("Registered mDNS service tempa-transfer on port %s", port)


def unregister_service() -> None:
    global _service
    if _service:
        try:
            _service.close()
        except Exception:
            pass
        _service = None
