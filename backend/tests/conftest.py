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
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


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
