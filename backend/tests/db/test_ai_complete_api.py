"""POST /api/v1/ai/complete through the real app: authentication, the response, and error codes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.ai.base import AIProviderError
from app.services.ai.service import AIService
from tests.ai_stub import StubProvider
from tests.conftest import build_app, make_settings
from tests.db.conftest import register

BODY = {
    "file_path": "app/main.py",
    "language": "python",
    "prefix": "def calculate_total(price, quantity):\n",
    "suffix": "",
}


def _client(
    database_url: str, client_factory: Callable[[FastAPI], TestClient], stub: StubProvider
) -> TestClient:
    app = build_app(database_url=database_url, ai_enabled=True)
    app.state.ai_service = AIService(make_settings(ai_enabled=True, database_url=database_url), provider=stub)
    return client_factory(app)


def test_signed_in_users_get_a_completion(
    database_url: str, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    stub = StubProvider(answers=[{"completion": "    return price * quantity"}])
    client = _client(database_url, client_factory, stub)
    register(client)
    response = client.post("/api/v1/ai/complete", json=BODY)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "completion": "    return price * quantity",
        "provider": "stub",
        "model": "stub-model",
    }


def test_anonymous_requests_are_refused_without_a_provider_call(
    database_url: str, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    stub = StubProvider()
    client = _client(database_url, client_factory, stub)
    assert client.post("/api/v1/ai/complete", json=BODY).status_code == 401
    assert stub.requests == []


def test_provider_quota_errors_are_reported_with_their_code(
    database_url: str, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    stub = StubProvider(answers=[AIProviderError("no credit", code="ai_quota_exceeded")])
    client = _client(database_url, client_factory, stub)
    register(client)
    response = client.post("/api/v1/ai/complete", json=BODY)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ai_quota_exceeded"
