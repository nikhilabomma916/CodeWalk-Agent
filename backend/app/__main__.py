"""Run the API with ``python -m app`` using host/port/reload from settings."""

from __future__ import annotations

import uvicorn

from app.core.config import Environment, get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env is Environment.DEVELOPMENT,
        reload_dirs=["app"] if settings.env is Environment.DEVELOPMENT else None,
        log_config=None,  # app.core.logging configures logging
        proxy_headers=settings.is_production,
    )


if __name__ == "__main__":
    main()
