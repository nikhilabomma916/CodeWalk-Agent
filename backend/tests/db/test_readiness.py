"""Module 23: readiness reflects the database schema version."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.conftest import build_app

PRODUCTION = {"env": "production", "secret_key": "k" * 48, "cors_origins": []}


@pytest.fixture
def old_schema(engine: Engine) -> Iterator[None]:
    with engine.begin() as connection:
        current: str = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        connection.execute(text("UPDATE alembic_version SET version_num = 'c5d2e8f1a9b3'"))
    yield
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": current})


def checks(client: TestClient, path: str = "/api/v1/health/ready") -> tuple[int, dict[str, str]]:
    response = client.get(path)
    return response.status_code, {c["name"]: c["status"] for c in response.json()["checks"]}


def test_a_migrated_database_is_ready(
    database_url: str, engine: Engine, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    status, results = checks(
        client_factory(build_app(database_url=database_url, **PRODUCTION)),
    )
    assert status == 200
    assert results["database"] == "pass"
    assert results["schema"] == "pass"


def test_production_is_not_ready_on_an_old_schema(
    database_url: str, engine: Engine, client_factory: Callable[[FastAPI], TestClient], old_schema: None
) -> None:
    client = client_factory(build_app(database_url=database_url, **PRODUCTION))
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    schema = next(c for c in response.json()["checks"] if c["name"] == "schema")
    assert schema["status"] == "fail"
    assert schema["required"] is True
    assert "c5d2e8f1a9b3" in schema["detail"]
    assert client.get("/api/v1/health/live").status_code == 200  # alive, just not ready


def test_development_is_only_degraded_on_an_old_schema(
    database_url: str, engine: Engine, client_factory: Callable[[FastAPI], TestClient], old_schema: None
) -> None:
    response = client_factory(build_app(database_url=database_url)).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
