from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import __version__
from app.services.health import HealthCheckFailedError, HealthService


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


def test_health_reports_alive_without_unverified_dependencies(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "testing"
    assert body["uptime_seconds"] >= 0
    datetime.fromisoformat(body["timestamp"])
    # No database/AI checks are registered yet, so none may be claimed healthy.
    assert body["checks"] == []


def test_liveness_probe(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_required_check_failure_makes_service_unavailable(app: FastAPI, client: TestClient) -> None:
    health_service(app).register(StubCheck("database", required=True, behaviour="fail"))

    for path in ("/api/v1/health", "/api/v1/health/ready"):
        response = client.get(path)
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["checks"][0]["name"] == "database"
        assert body["checks"][0]["status"] == "fail"
        assert body["checks"][0]["detail"] == "connection refused"


def test_optional_check_failure_is_degraded(app: FastAPI, client: TestClient) -> None:
    service = health_service(app)
    service.register(StubCheck("database", required=True))
    service.register(StubCheck("ai_provider", required=False, behaviour="fail"))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    statuses = {check["name"]: check["status"] for check in body["checks"]}
    assert statuses == {"database": "pass", "ai_provider": "fail"}


def test_unexpected_check_error_does_not_leak_details(app: FastAPI, client: TestClient) -> None:
    health_service(app).register(StubCheck("database", required=True, behaviour="crash"))

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert "hunter2" not in response.text
    assert response.json()["checks"][0]["detail"] == "Check raised an unexpected error"


def test_hanging_check_times_out(
    client_factory: Callable[[FastAPI], TestClient],
) -> None:
    from app.application import create_app
    from tests.conftest import make_settings

    app = create_app(make_settings(health_check_timeout_seconds=0.05))
    health_service(app).register(StubCheck("vector_store", required=False, behaviour="hang"))
    client = client_factory(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    check = response.json()["checks"][0]
    assert check["status"] == "fail"
    assert check["detail"].startswith("Timed out")


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
