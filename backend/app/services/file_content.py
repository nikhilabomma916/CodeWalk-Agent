"""Derived attributes of stored file content (size, lines, hash, language)."""

from __future__ import annotations

import hashlib
import posixpath
from typing import Any

from app.services.languages import detect_language
from app.services.project_intelligence.project_analyzer import count_lines


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def file_values(path: str, content: str | None, size: int | None = None) -> dict[str, Any]:
    """Column values for a file record. ``content`` is None for binary/oversized files."""
    return {
        "path": path,
        "name": posixpath.basename(path),
        "language": detect_language(path).value,
        "content": content,
        "size": len(content.encode("utf-8")) if content is not None else (size or 0),
        "line_count": count_lines(content) if content is not None else 0,
        "content_hash": content_hash(content) if content is not None else None,
        "structure": None,
    }
