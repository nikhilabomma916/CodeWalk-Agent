"""Reusable validated types for API boundaries."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.core.exceptions import UnsafePathError
from app.services.project_intelligence.scanner import is_secret_path
from app.utils.paths import normalize_relative_path

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
MAX_SEGMENT_LENGTH = 255
# Invisible or direction-changing characters (bidi overrides such as U+202E, zero-width spaces,
# line/paragraph separators, C1 controls) make names display as something else ("Trojan Source"):
# a file could look like another, or two different paths could look identical.
_DECEPTIVE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


def _has_deceptive_characters(value: str) -> bool:
    return any(unicodedata.category(character) in _DECEPTIVE_CATEGORIES for character in value)


def _validate_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be empty")
    if _CONTROL_CHARACTERS.search(value) or _has_deceptive_characters(value):
        raise ValueError("must not contain control or invisible formatting characters")
    return value


def _validate_relative_path(value: str) -> str:
    try:
        normalized = normalize_relative_path(value).as_posix()
    except UnsafePathError as exc:
        raise ValueError(exc.message) from None
    if any(len(segment) > MAX_SEGMENT_LENGTH for segment in normalized.split("/")):
        raise ValueError(f"path segments must be at most {MAX_SEGMENT_LENGTH} characters")
    if _CONTROL_CHARACTERS.search(normalized) or any(c in normalized for c in '<>:"|?*'):
        raise ValueError("path contains characters that are not allowed")
    if _has_deceptive_characters(normalized):
        raise ValueError("path contains invisible or direction-changing characters")
    if any(segment != segment.strip() for segment in normalized.split("/")):
        raise ValueError("path segments must not start or end with spaces")
    return normalized


def _validate_file_path(value: str) -> str:
    normalized = _validate_relative_path(value)
    if is_secret_path(normalized):
        raise ValueError("secret files such as .env are not stored")
    return normalized


def _validate_project_name(value: str) -> str:
    value = _validate_name(value)
    if "/" in value or "\\" in value:
        raise ValueError("must not contain slashes")
    return value


DisplayName = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_validate_name)]
ProjectName = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_validate_project_name)]
RelativePath = Annotated[str, Field(min_length=1, max_length=1024), AfterValidator(_validate_relative_path)]
ProjectFilePath = Annotated[str, Field(min_length=1, max_length=1024), AfterValidator(_validate_file_path)]


class Page[ItemT](BaseModel):
    items: list[ItemT]
    total: int
    limit: int
    offset: int
