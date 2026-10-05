"""Module 21 units: deceptive path characters, and the shared limiter's fallback."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine

from app.core.rate_limit import AttemptLimiter, DatabaseAttemptLimiter, make_limiter
from app.schemas.common import ProjectFilePath, ProjectName, RelativePath

FILE_PATH = TypeAdapter(ProjectFilePath)
RELATIVE = TypeAdapter(RelativePath)
NAME = TypeAdapter(ProjectName)


@pytest.mark.parametrize(
    "value",
    [
        "invoice" + chr(0x202E) + "gpj.py",  # right-to-left override: displays as "invoiceyp.jpg"
        "a" + chr(0x200B) + "b.py",  # zero-width space: looks like "ab.py"
        "a" + chr(0x2066) + "b.py",  # left-to-right isolate
        "a" + chr(0xFEFF) + "b.py",  # zero-width no-break space
        "line" + chr(0x2028) + "sep.py",
        "para" + chr(0x2029) + "sep.py",
        "c1\u0085.py",  # C1 control (next line)
        " lead.py",
        "trail.py ",
        "dir /x.py",
    ],
)
def test_deceptive_paths_are_rejected(value: str) -> None:
    for adapter in (FILE_PATH, RELATIVE):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


@pytest.mark.parametrize(
    "value", ["src/app.py", "docs/résumé.md", "项目/文件.py", "a b/c d.py", "emoji_🙂.txt"]
)
def test_ordinary_unicode_paths_are_kept(value: str) -> None:
    assert FILE_PATH.validate_python(value) == value


def test_project_names_reject_invisible_characters() -> None:
    with pytest.raises(ValidationError):
        NAME.validate_python("Shop" + chr(0x202E) + "")
    assert NAME.validate_python("  Café shop ") == "Café shop"


def test_limiter_choice() -> None:
    assert isinstance(make_limiter(None, 3, 60, namespace="x"), AttemptLimiter)
    engine = create_engine("sqlite://")
    assert isinstance(make_limiter(engine, 3, 60, namespace="x"), DatabaseAttemptLimiter)


def test_shared_limiter_falls_back_to_a_process_limit_when_the_database_fails() -> None:
    """No PostgreSQL (here: SQLite without the table or advisory locks): a limit still applies."""
    limiter = DatabaseAttemptLimiter(create_engine("sqlite://"), 2, 60, namespace="login")
    assert limiter.acquire("k") is None
    assert limiter.acquire("k") is None
    assert limiter.acquire("k") is not None
    limiter.reset("k")
    assert limiter.acquire("k") is None
