"""Live integration checks against running backend and frontend servers.

Start both services first (``npm run dev``), then run ``npm run test:integration``.
Override targets with CODEWALK_STACK_API_URL / CODEWALK_STACK_FRONTEND_URL.
Unlike the unit suites, these tests fail (rather than skip) when a service is down,
because they are only run deliberately against a live stack.
"""

from __future__ import annotations

import os

import httpx
import pytest

API_URL = os.environ.get("CODEWALK_STACK_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
FRONTEND_URL = os.environ.get("CODEWALK_STACK_FRONTEND_URL", "http://localhost:3000").rstrip("/")
FRONTEND_ORIGIN = os.environ.get("CODEWALK_STACK_FRONTEND_ORIGIN", "http://localhost:3000")


@pytest.fixture(scope="module")
def http() -> httpx.Client:
    with httpx.Client(timeout=10.0) as client:
        yield client


def test_backend_health_is_real_and_structured(http: httpx.Client) -> None:
    response = http.get(f"{API_URL}/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert {"service", "version", "environment", "timestamp", "uptime_seconds", "checks"} <= body.keys()
    assert response.headers["X-Request-ID"]


def test_backend_allows_frontend_origin(http: httpx.Client) -> None:
    preflight = http.options(
        f"{API_URL}/health",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_backend_rejects_foreign_origin(http: httpx.Client) -> None:
    response = http.get(f"{API_URL}/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_backend_error_contract(http: httpx.Client) -> None:
    missing = http.get(f"{API_URL}/definitely-not-a-route")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    # Larger than the default CODEWALK_MAX_REQUEST_BODY_BYTES (6 MiB).
    too_large = http.post(f"{API_URL}/health", content=b"x" * (7 * 1024 * 1024))
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "payload_too_large"


def test_frontend_serves_workspace(http: httpx.Client) -> None:
    page = http.get(FRONTEND_URL)
    assert page.status_code == 200
    assert "<title>CodeWalk Agent</title>" in page.text


def test_frontend_serves_self_hosted_monaco(http: httpx.Client) -> None:
    loader = http.get(f"{FRONTEND_URL}/monaco/vs/loader.js")
    assert loader.status_code == 200
    assert len(loader.content) > 1000
