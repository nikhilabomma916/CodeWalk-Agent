from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import __version__
from app.services.health import HealthCheckFailedError, HealthService
from tests.conftest import build_app


class StubCheck:
    def __init__(self, name: str, *, required: bool, behaviour: str = "pass") -> None:
        self.name = name
        self.required = required
        self.behaviour = behaviour

    async def check(self) -> None:
        if self.behaviour == "fail":
            raise HealthCheckFailedError("connection refused")
        if self.behaviour == "crash":
            raise RuntimeError("postgres://admin:hunter2@db:5432 exploded")
        if self.behaviour == "hang":
            await asyncio.sleep(10)


def health_service(app: FastAPI) -> HealthService:
    service: HealthService = app.state.health_service
    return service


def check(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in body["checks"] if item["name"] == name)


def test_health_reports_database_as_not_configured(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "testing"
    assert body["uptime_seconds"] >= 0
    datetime.fromisoformat(body["timestamp"])
    # No database is configured in unit tests: reported as such, never as healthy.
    database = check(body, "database")
    assert database["status"] == "not_configured"
    assert database["required"] is False
    assert database["detail"] == "CODEWALK_DATABASE_URL is not set"


def test_liveness_probe(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_required_check_failure_makes_service_unavailable(app: FastAPI, client: TestClient) -> None:
    health_service(app).register(StubCheck("primary", required=True, behaviour="fail"))

    for path in ("/api/v1/health", "/api/v1/health/ready"):
        response = client.get(path)
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        assert check(body, "primary")["status"] == "fail"
        assert check(body, "primary")["detail"] == "connection refused"


def test_optional_check_failure_is_degraded(app: FastAPI, client: TestClient) -> None:
    service = health_service(app)
    service.register(StubCheck("primary", required=True))
    service.register(StubCheck("ai_provider", required=False, behaviour="fail"))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    statuses = {item["name"]: item["status"] for item in body["checks"]}
    assert statuses == {"database": "not_configured", "primary": "pass", "ai_provider": "fail"}


def test_unexpected_check_error_does_not_leak_details(app: FastAPI, client: TestClient) -> None:
    health_service(app).register(StubCheck("primary", required=True, behaviour="crash"))

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert "hunter2" not in response.text
    assert check(response.json(), "primary")["detail"] == "Check raised an unexpected error"


def test_hanging_check_times_out(client_factory: Callable[[FastAPI], TestClient]) -> None:
    app = build_app(health_check_timeout_seconds=0.05)
    health_service(app).register(StubCheck("vector_store", required=False, behaviour="hang"))
    client = client_factory(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    result = check(response.json(), "vector_store")
    assert result["status"] == "fail"
    assert result["detail"].startswith("Timed out")


def test_request_id_is_generated_and_propagated(client: TestClient) -> None:
    generated = client.get("/api/v1/health/live").headers["X-Request-ID"]
    assert len(generated) == 32

    supplied = "frontend-req-12345"
    echoed = client.get("/api/v1/health/live", headers={"X-Request-ID": supplied})
    assert echoed.headers["X-Request-ID"] == supplied

    # Malformed ids are replaced rather than reflected.
    injected = client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id\r\n"})
    assert injected.headers["X-Request-ID"] != "bad id"


def test_security_headers_present(client: TestClient) -> None:
    headers = client.get("/api/v1/health/live").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
