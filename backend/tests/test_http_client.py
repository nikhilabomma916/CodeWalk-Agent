from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from app.integrations.http_client import (
    ExternalHTTPClient,
    ExternalServiceBadResponseError,
    ExternalServiceError,
    ExternalServiceHTTPError,
    ExternalServiceTimeoutError,
    ExternalServiceUnavailableError,
)


class Completion(BaseModel):
    text: str


def client_for(handler: httpx.MockTransport) -> ExternalHTTPClient:
    return ExternalHTTPClient(
        "ai_provider", base_url="https://provider.test", timeout_seconds=1.0, transport=handler
    )


async def test_parses_valid_response() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"text": "hello"}))
    async with client_for(transport) as client:
        result = await client.request_json("POST", "/complete", Completion, json={"prompt": "hi"})
    assert result == Completion(text="hello")


async def test_http_error_status() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(502, text="bad gateway"))
    async with client_for(transport) as client:
        with pytest.raises(ExternalServiceHTTPError) as excinfo:
            await client.request_json("GET", "/x", Completion)
    assert excinfo.value.status_code == 502


@pytest.mark.parametrize("body", [b"not json", b'{"unexpected": 1}'])
async def test_malformed_response(body: bytes) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    async with client_for(transport) as client:
        with pytest.raises(ExternalServiceBadResponseError):
            await client.request_json("GET", "/x", Completion)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.ReadTimeout("slow"), ExternalServiceTimeoutError),
        (httpx.ConnectError("refused"), ExternalServiceUnavailableError),
    ],
)
async def test_transport_failures_are_typed(exc: Exception, expected: type[ExternalServiceError]) -> None:
    def raise_error(_: httpx.Request) -> httpx.Response:
        raise exc

    async with client_for(httpx.MockTransport(raise_error)) as client:
        with pytest.raises(expected) as excinfo:
            await client.request_json("GET", "/x", Completion)
    assert excinfo.value.service == "ai_provider"


async def test_error_message_does_not_include_credentials() -> None:
    def raise_error(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed for https://user:sk-123@provider.test")

    client = ExternalHTTPClient(
        "ai_provider",
        base_url="https://provider.test",
        timeout_seconds=1.0,
        headers={"Authorization": "Bearer sk-123"},
        transport=httpx.MockTransport(raise_error),
    )
    async with client:
        with pytest.raises(ExternalServiceUnavailableError) as excinfo:
            await client.request_json("GET", "/x", Completion)
    assert "sk-123" not in str(excinfo.value)
