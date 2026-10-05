"""Run the API with ``python -m app`` using host/port/reload from settings (Vercel: its PORT)."""

from __future__ import annotations

import os
from collections.abc import Mapping

import uvicorn

from app.core.config import Environment, Settings, get_settings


def listen_port(settings: Settings, environ: Mapping[str, str] = os.environ) -> int:
    """CODEWALK_PORT, except in a Vercel container, which must listen on Vercel's PORT (default 80)."""
    if settings.on_vercel:
        return int(environ.get("PORT") or 80)
    return settings.port


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=listen_port(settings),
        reload=settings.env is Environment.DEVELOPMENT,
        reload_dirs=["app"] if settings.env is Environment.DEVELOPMENT else None,
        log_config=None,  # app.core.logging configures logging
        proxy_headers=settings.is_production,
        # SIGTERM: stop accepting connections, give in-flight requests this long, then run the
        # lifespan shutdown (TypeScript worker, database pool) within the host's grace period.
        timeout_graceful_shutdown=settings.shutdown_timeout_seconds,
    )


if __name__ == "__main__":
    main()
