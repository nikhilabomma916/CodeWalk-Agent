"""A configured but unreachable database must fail safely (no PostgreSQL needed)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import build_app

# Port 9 (discard) is closed on test machines; the password must never leak.
UNREACHABLE = "postgresql+psycopg://codewalk:s3cr3t-pw@127.0.0.1:9/codewalk"


def test_unreachable_database_fails_safely(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(build_app(database_url=UNREACHABLE, database_connect_timeout_seconds=1))

    # Without a session the request is rejected before the database is used.
    assert client.get("/api/v1/projects").status_code == 401

    # A session cookie must be checked against the database, which is down.
    client.cookies.set("codewalk_session", "a" * 43)
    response = client.get("/api/v1/projects")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "s3cr3t" not in response.text
    assert "127.0.0.1" not in response.text

    health = client.get("/api/v1/health")
    assert health.status_code == 200  # the API still serves analysis
    body = health.json()
    assert body["status"] == "degraded"
    database = next(check for check in body["checks"] if check["name"] == "database")
    assert database == {**database, "status": "fail", "detail": "Database is not reachable"}
    assert "s3cr3t" not in health.text

    analysis = client.post("/api/v1/analysis/code", json={"code": "x = 1\n", "language": "python"})
    assert analysis.status_code == 200
