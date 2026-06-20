from __future__ import annotations

import uvicorn

from tempa.api.app import create_app
from tempa.settings import get_settings


def main() -> None:
    settings = get_settings()
    app = create_app()
    uvicorn.run(
        app,
        host=settings.tempa_bind_host,
        port=settings.tempa_daemon_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
