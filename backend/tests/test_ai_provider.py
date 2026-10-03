"""The Anthropic provider, exercised through the real ``anthropic`` SDK with a mock HTTP transport.

No network and no real credential: these tests check the request the SDK sends
and how responses and failures are mapped. They do not prove a live provider
works (see the live smoke test, run only when a credential is configured).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from anthropic import DefaultHttpxClient

from app.services.ai.base import (
    AIContextTooLargeError,
    AIError,
    AIMalformedResponseError,
    AIProviderError,
    AIRateLimitedError,
    AIRefusedError,
    AITimeoutError,
    AIUnavailableError,
    StructuredRequest,
)
from app.services.ai.providers import UnknownProviderError, create_provider
from app.services.ai.providers.anthropic import DEFAULT_MODEL, AnthropicProvider
from tests.conftest import make_settings

FAKE_KEY = "sk-ant-test-not-a-real-key"
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def message(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": DEFAULT_MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }


def provider_with(handler: Callable[[httpx2.Request], httpx2.Response], **kwargs: Any) -> AnthropicProvider:
    return AnthropicProvider(
        api_key=FAKE_KEY,
        timeout_seconds=5,
        max_retries=0,
        http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
        **kwargs,
    )


def request() -> StructuredRequest:
    return StructuredRequest(
        system="system text",
        user="user text",
        schema=SCHEMA,
        max_tokens=1000,
        timeout_seconds=5,
        effort="high",
    )


def test_successful_structured_request() -> None:
    sent: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        sent.append(req)
        return httpx2.Response(200, json=message('{"answer": "42"}'), headers={"request-id": "req_123"})

    result = provider_with(handler).generate_structured(request())
    assert result.data == {"answer": "42"}
    assert result.model == DEFAULT_MODEL
    assert result.usage == {"input_tokens": 11, "output_tokens": 7}

    body = json.loads(sent[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "system text"
    assert body["messages"] == [{"role": "user", "content": "user text"}]
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "high"}
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in sent[0].headers["anthropic-beta"]
    assert sent[0].headers["x-api-key"] == FAKE_KEY  # sent to the provider only
    assert "thinking" not in body  # adaptive by default on current models


def test_models_without_effort_or_fallback_support() -> None:
    sent: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        sent.append(req)
        return httpx2.Response(200, json=message('{"answer": "x"}'))

    provider_with(handler, model="claude-haiku-4-5").generate_structured(request())
    body = json.loads(sent[0].content)
    assert "effort" not in body["output_config"]
    assert "fallbacks" not in body


@pytest.mark.parametrize(
    ("text", "stop_reason", "error"),
    [
        ("not json at all", "end_turn", AIMalformedResponseError),
        ('["a list"]', "end_turn", AIMalformedResponseError),
        ('{"answer": "cut', "max_tokens", AIMalformedResponseError),
        ("", "refusal", AIRefusedError),
    ],
)
def test_unusable_answers(text: str, stop_reason: str, error: type[AIError]) -> None:
    provider = provider_with(lambda _: httpx2.Response(200, json=message(text, stop_reason)))
    with pytest.raises(error):
        provider.generate_structured(request())


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, AIProviderError),
        (401, AIProviderError),
        (403, AIProviderError),
        (404, AIProviderError),
        (413, AIContextTooLargeError),
        (429, AIRateLimitedError),
        (500, AIUnavailableError),
        (529, AIUnavailableError),
    ],
)
def test_http_errors_are_normalized(status: int, error: type[AIError]) -> None:
    body = {"type": "error", "error": {"type": "api_error", "message": f"secret detail {FAKE_KEY}"}}
    provider = provider_with(lambda _: httpx2.Response(status, json=body))
    with pytest.raises(error) as excinfo:
        provider.generate_structured(request())
    assert FAKE_KEY not in excinfo.value.message
    assert "secret detail" not in excinfo.value.message


def test_timeout_and_network_failures() -> None:
    def timeout(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=req)

    def refused(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=req)

    with pytest.raises(AITimeoutError):
        provider_with(timeout).generate_structured(request())
    with pytest.raises(AIUnavailableError):
        provider_with(refused).generate_structured(request())


def test_status_never_calls_the_provider() -> None:
    calls: list[httpx2.Request] = []
    configured = provider_with(lambda r: calls.append(r) or httpx2.Response(500))  # type: ignore[func-returns-value]
    assert configured.status().configured is True
    missing = AnthropicProvider(api_key=None)
    state = missing.status()
    assert state.configured is False
    assert "ANTHROPIC_API_KEY" in (state.detail or "")
    assert calls == []
    with pytest.raises(AIProviderError):
        missing.generate_structured(request())


def test_registry_selects_provider_and_credentials() -> None:
    settings = make_settings(ai_enabled=True, ai_api_key="sk-ant-from-settings", ai_model="claude-sonnet-5-5")
    provider = create_provider(settings)
    assert provider.name == "anthropic"
    assert provider.model == "claude-sonnet-5-5"
    assert provider.status().configured

    fallback = create_provider(make_settings(ai_enabled=True, ANTHROPIC_API_KEY="sk-ant-env"))
    assert fallback.status().configured
    assert fallback.model == DEFAULT_MODEL

    with pytest.raises(UnknownProviderError):
        create_provider(make_settings(ai_enabled=True, ai_provider="made-up"))
