"""Error contract: every failure returns ``{"error": {code, message, request_id, ...}}``."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.exceptions import NotFoundError
from tests.conftest import FRONTEND_ORIGIN, build_app


class ProbePayload(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    count: int = Field(ge=0)


def app_with_probe_routes(max_body_bytes: int = 1024) -> FastAPI:
    """The real application plus routes that exercise each error path.

    No public endpoint accepts a request body yet, so these routes stand in
    for future feature routes while using the production handlers/middleware.
    """
    app = build_app(max_request_body_bytes=max_body_bytes)
    probe = APIRouter(prefix="/api/v1/_probe")

    @probe.post("/echo")
    async def echo(payload: ProbePayload) -> ProbePayload:
        return payload

    @probe.get("/missing")
    async def missing() -> None:
        raise NotFoundError("Project not found.")

    @probe.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internals at C:\\srv\\app\\db.py password=hunter2")

    app.include_router(probe)
    return app


def assert_error_shape(body: dict[str, object], code: str) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert error["message"]
    assert isinstance(error["request_id"], str)
    return error


def iter_chunks(size: int, chunk: int = 256) -> Iterator[bytes]:
    sent = 0
    while sent < size:
        yield b"a" * chunk
        sent += chunk


def test_unknown_route_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = assert_error_shape(response.json(), "not_found")
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_wrong_method_returns_405(client: TestClient) -> None:
    response = client.post("/api/v1/health")
    assert response.status_code == 405
    assert_error_shape(response.json(), "method_not_allowed")


def test_valid_request_succeeds(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes())
    response = client.post("/api/v1/_probe/echo", json={"name": "demo", "count": 3})
    assert response.status_code == 200
    assert response.json() == {"name": "demo", "count": 3}


def test_invalid_request_returns_422_without_echoing_input(
    client_factory: Callable[[FastAPI], TestClient],
) -> None:
    client = client_factory(app_with_probe_routes())
    response = client.post("/api/v1/_probe/echo", json={"name": "sk-secret-value-toolong!!", "count": -1})

    assert response.status_code == 422
    error = assert_error_shape(response.json(), "validation_error")
    details = error["details"]
    assert isinstance(details, list)
    locations = {tuple(d["location"]) for d in details}
    assert locations == {("body", "name"), ("body", "count")}
    assert "sk-secret-value" not in response.text


def test_malformed_json_returns_422(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes())
    response = client.post(
        "/api/v1/_probe/echo", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert_error_shape(response.json(), "validation_error")


def test_app_error_maps_to_status_and_code(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes())
    response = client.get("/api/v1/_probe/missing")
    assert response.status_code == 404
    error = assert_error_shape(response.json(), "not_found")
    assert error["message"] == "Project not found."


def test_unhandled_error_is_generic_and_keeps_cors(
    client_factory: Callable[[FastAPI], TestClient],
) -> None:
    client = client_factory(app_with_probe_routes())
    response = client.get("/api/v1/_probe/crash", headers={"Origin": FRONTEND_ORIGIN})

    assert response.status_code == 500
    error = assert_error_shape(response.json(), "internal_error")
    assert error["message"] == "An unexpected error occurred."
    for leaked in ("hunter2", "db.py", "Traceback", "RuntimeError"):
        assert leaked not in response.text
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_declared_oversized_body_is_rejected(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes(max_body_bytes=100))
    response = client.post(
        "/api/v1/_probe/echo", content=b"x" * 101, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert_error_shape(response.json(), "payload_too_large")


def test_streamed_oversized_body_is_rejected(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes(max_body_bytes=1000))
    response = client.post(
        "/api/v1/_probe/echo",
        content=iter_chunks(5000),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert_error_shape(response.json(), "payload_too_large")


def _padded_json(size: int) -> bytes:
    """A valid probe payload of exactly ``size`` bytes (JSON allows trailing whitespace)."""
    body = b'{"name": "demo", "count": 3}'
    return body + b" " * (size - len(body))


def test_body_exactly_at_the_limit_is_accepted(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes(max_body_bytes=1000))
    response = client.post(
        "/api/v1/_probe/echo", content=_padded_json(1000), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200
    assert response.json() == {"name": "demo", "count": 3}


def test_body_one_byte_over_the_limit_is_rejected(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes(max_body_bytes=1000))
    response = client.post(
        "/api/v1/_probe/echo", content=_padded_json(1001), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    error = assert_error_shape(response.json(), "payload_too_large")
    assert error["message"] == "Request body exceeds the 1000 byte limit."


def test_streamed_body_at_the_limit_is_accepted(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(app_with_probe_routes(max_body_bytes=1000))
    body = _padded_json(1000)
    response = client.post(
        "/api/v1/_probe/echo",
        content=(body[i : i + 100] for i in range(0, len(body), 100)),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
