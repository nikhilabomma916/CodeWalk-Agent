"""Fixtures for tests against a real PostgreSQL database.

Set CODEWALK_TEST_DATABASE_URL to a *dedicated* database whose name ends in
``_test``. The schema is built with the real Alembic migrations (downgrade to
base, then upgrade to head) and all rows are truncated after each test. Without
the variable these tests are skipped, never faked.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.conftest import build_app

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Fail fast instead of hanging when the server (or one resolved address) does not answer.
CONNECT_ARGS = {"connect_timeout": 5}


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("CODEWALK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CODEWALK_TEST_DATABASE_URL is not set; PostgreSQL tests were not run")
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        pytest.fail(f"Refusing to use database {name!r}: test database names must end with '_test'")
    engine = create_engine(url, connect_args=CONNECT_ARGS)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Test database is unreachable ({type(exc).__name__}); PostgreSQL tests were not run")
    finally:
        engine.dispose()
    config = alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url, connect_args=CONNECT_ARGS)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    uses_database = "engine" in request.fixturenames or "database_url" in request.fixturenames
    engine: Engine | None = request.getfixturevalue("engine") if uses_database else None
    yield
    if engine is not None:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE projects, files, analyses, diagnostics CASCADE"))


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def db_app(database_url: str, workspace: Path, engine: Engine) -> FastAPI:
    return build_app(database_url=database_url, workspace_root=str(workspace))


@pytest.fixture
def api(db_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(db_app) as client:
        yield client
