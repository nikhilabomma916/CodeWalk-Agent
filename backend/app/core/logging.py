"""Logging configuration.

Every record carries the current request id (when inside a request) so that
API errors can be correlated with the ``request_id`` returned to clients.
"""

from __future__ import annotations

import json
import logging
import re
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


# Defense in depth (Module 23): code never logs credentials on purpose, but a third-party message or
# a traceback might. Every formatted line is scrubbed of these shapes before it is written.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (re.compile(r"\b(sk-ant-|sk-or-v1-|sk-proj-|sk-)[A-Za-z0-9_-]{16,}"), r"\1[redacted]"),
    (re.compile(r"\b(gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"), r"\1[redacted]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "AIza[redacted]"),
    (re.compile(r"\bpa-[A-Za-z0-9_-]{30,}"), "pa-[redacted]"),
    (re.compile(r"\bv1\.[0-9a-f]{16}\.[A-Za-z0-9_-]{20,}"), "v1.[redacted]"),  # stored token ciphertext
    # user:password@ in URLs (database URLs, proxies)
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^:/@\s]+):[^@\s/]+@"), r"\1:[redacted]@"),
    # key=value / "key": "value" for secret-looking names
    (
        re.compile(
            r"(?i)\b([a-z_]*(?:api_key|secret|password|access_token|client_secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&]{4,}"
        ),
        r"\1[redacted]",
    ),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formats with ``inner`` (text or JSON), then removes credential-shaped values."""

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.inner.format(record))


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
    handler.setFormatter(RedactingFormatter(formatter))
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
