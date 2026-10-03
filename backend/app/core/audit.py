"""Security audit events, logged to the ``app.security`` logger.

One line per event: ``security.<event> key=value ...``. Callers pass identifiers,
codes, and counts only, never passwords, tokens, API keys, file contents, or model
output. Values are reduced to a safe character set and bounded in length, so a
hostile value (e.g. a crafted email or path) cannot forge extra log fields or lines.
The current request id is attached by the logging configuration.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

security_logger = logging.getLogger("app.security")

_UNSAFE = re.compile(r"[^A-Za-z0-9._:/@-]")
MAX_VALUE_CHARS = 120


def _clean(value: Any) -> str:
    text = _UNSAFE.sub("?", str(value))
    return text[:MAX_VALUE_CHARS]


def fingerprint(value: str) -> str:
    """A short, stable, non-reversible tag for a personal value such as an email address."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:12]


def audit(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    parts = " ".join(f"{key}={_clean(value)}" for key, value in fields.items() if value is not None)
    security_logger.log(level, "security.%s %s", _clean(event), parts)
