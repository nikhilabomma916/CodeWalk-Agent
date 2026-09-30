"""Logging configuration.

Every record carries the current request id (when inside a request) so that
API errors can be correlated with the ``request_id`` returned to clients.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, suitable for log shippers."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_HANDLER_NAME = "codewalk-console"
TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"


def configure_logging(settings: Settings) -> None:
    """Install (or replace) the CodeWalk console handler on the root logger.

    Idempotent: calling it again, e.g. when a second app is created in tests,
    swaps only the handler it owns and leaves foreign handlers untouched.
    """
    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_format == "json" else logging.Formatter(TEXT_FORMAT)
    )
    handler = logging.StreamHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == _HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # uvicorn installs its own handlers when started from the CLI; route its
    # messages through ours instead. Our middleware writes access logs, so
    # uvicorn's access logger is silenced.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(settings.log_level)
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False

    # httpx logs full request URLs at INFO; some providers put API keys in query strings.
    logging.getLogger("httpx").setLevel(logging.WARNING)
