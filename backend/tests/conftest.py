from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application import create_app
from app.core.config import Settings

FRONTEND_ORIGIN = "http://localhost:3000"


def make_settings(**overrides: Any) -> Settings:
    """Settings isolated from the developer's real environment and .env files."""
    values: dict[str, Any] = {
        "env": "testing",
        "cors_origins": [FRONTEND_ORIGIN],
        "log_level": "WARNING",
    }
    values.update(overrides)
    # Keep the source limit below a body limit shrunk by a test.
    if "max_request_body_bytes" in overrides and "max_source_bytes" not in overrides:
        values["max_source_bytes"] = max(1, overrides["max_request_body_bytes"] // 2)
    return Settings(_env_file=None, **values)


def build_app(**overrides: Any) -> FastAPI:
    """The real application with isolated settings (no background TypeScript warm-up)."""
    return create_app(make_settings(**overrides), warm_up=False)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings, warm_up=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_factory() -> Iterator[Callable[[FastAPI], TestClient]]:
    clients: list[TestClient] = []

    def factory(application: FastAPI) -> TestClient:
        test_client = TestClient(application, raise_server_exceptions=False)
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield factory
    for test_client in clients:
        test_client.__exit__(None, None, None)
