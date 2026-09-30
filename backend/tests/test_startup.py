from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.application import create_app
from tests.conftest import make_settings


def test_lifespan_logs_startup_and_shutdown(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(make_settings(log_level="INFO"))
    with caplog.at_level(logging.INFO, logger="app.application"), TestClient(app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
    messages = [record.getMessage() for record in caplog.records if record.name == "app.application"]
    assert any(m.startswith("Starting CodeWalk Agent API") for m in messages)
    assert any(m.startswith("Shutting down") for m in messages)


def test_startup_log_does_not_contain_secrets(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(make_settings(log_level="INFO", secret_key="s" * 40, ai_api_key="sk-live-xyz"))
    with caplog.at_level(logging.DEBUG), TestClient(app):
        pass
    assert "sk-live-xyz" not in caplog.text
    assert "s" * 40 not in caplog.text
