"""Module 19: OpenAI, Anthropic, Gemini, OpenRouter and Ollama behind one AIProvider contract.

Every provider is exercised through its real HTTP code with a mock transport: no network, no real
credential. These tests check the request each provider sends and how its answers and failures are
normalized; they do not prove a live account works (see tests/test_live_ai_provider.py).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.services.ai.base import (
    AIContextTooLargeError,
    AIError,
    AIMalformedResponseError,
    AIProviderError,
    AIRateLimitedError,
    AITimeoutError,
    AIUnavailableError,
    StructuredRequest,
)
from app.services.ai.outputs import ModelExplanation
from app.services.ai.providers import PROVIDERS, UnknownProviderError, create_provider
from app.services.ai.providers.openai_compatible import (
    GEMINI,
    GEMINI_BASE_URL,
    OLLAMA,
    OPENAI,
    OPENROUTER,
    OPENROUTER_BASE_URL,
    CompatibleProfile,
    OpenAICompatibleProvider,
)
from app.services.ai.service import AIService
from app.services.retrieval.providers import create_embedding_provider
from tests.ai_stub import StubProvider
from tests.conftest import make_settings

KEYS = {
    "openai": ("OPENAI_API_KEY", "sk-openai-test-key-0001"),
    "anthropic": ("ANTHROPIC_API_KEY", "sk-ant-test-key-0002"),
    "gemini": ("GEMINI_API_KEY", "gemini-test-key-0003"),
    "openrouter": ("OPENROUTER_API_KEY", "sk-or-test-key-0004"),
}
REQUEST = StructuredRequest(
    system="Answer in JSON.",
    user="What does this do?",
    schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    max_tokens=1000,
    timeout_seconds=5,
    effort="high",
)


def completion(content: Any, **extra: Any) -> dict[str, Any]:
    return {
        "id": "gen-1",
        "model": "served-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(content)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, **extra},
    }


def provider(
    profile: CompatibleProfile,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str | None = "test-key",
    base_url: str | None = None,
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key=api_key,
        model="test-model",
        base_url=base_url,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
        profile=profile,
    )


def capture() -> tuple[dict[str, Any], Callable[[httpx.Request], httpx.Response]]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion({"answer": "ok"}))

    return seen, handler


# --- selection and configuration ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["openai", "gemini", "openrouter", "ollama", "anthropic"])
def test_each_provider_is_selected_explicitly(name: str) -> None:
    env = {KEYS[name][0]: KEYS[name][1]} if name in KEYS else {}
    chosen = create_provider(make_settings(ai_provider=name, ai_model="test-model", **env))
    assert chosen.name == name
    assert chosen.status().configured


def test_provider_names_are_case_insensitive_and_unknown_ones_are_refused() -> None:
    assert (
        create_provider(make_settings(ai_provider=" Gemini ", ai_model="m", GEMINI_API_KEY="k")).name
        == "gemini"
    )
    with pytest.raises(UnknownProviderError):
        create_provider(make_settings(ai_provider="openai-then-gemini"))
    service = AIService(make_settings(ai_enabled=True, ai_provider="mystery"))
    assert service.provider is None
    detail = service.status().detail or ""
    assert "mystery" in detail
    assert all(name in detail for name in PROVIDERS)


@pytest.mark.parametrize(
    ("name", "env", "hint"),
    [
        ("gemini", {}, "GEMINI_API_KEY"),
        ("openrouter", {}, "OPENROUTER_API_KEY"),
        ("gemini", {"GEMINI_API_KEY": "k"}, "CODEWALK_AI_MODEL"),
        ("openrouter", {"OPENROUTER_API_KEY": "k"}, "OPENROUTER_MODEL"),
        ("ollama", {}, "OLLAMA_MODEL"),
    ],
)
def test_missing_key_or_model_is_reported_without_a_call(name: str, env: dict[str, str], hint: str) -> None:
    model = "m" if "API_KEY" in hint else None
    status = create_provider(make_settings(ai_provider=name, ai_model=model, **env)).status()
    assert not status.configured
    assert hint in (status.detail or "")


def test_ollama_needs_no_key_and_no_model_is_ever_assumed() -> None:
    ollama = create_provider(make_settings(ai_provider="ollama", OLLAMA_MODEL="llama3.1:8b"))
    assert ollama.status().configured
    assert ollama.model == "llama3.1:8b"
    for name in ("gemini", "openrouter", "ollama"):
        assert (
            create_provider(make_settings(ai_provider=name, GEMINI_API_KEY="k", OPENROUTER_API_KEY="k")).model
            == ""
        )


def test_provider_specific_model_wins_over_the_generic_one() -> None:
    settings = make_settings(ai_provider="openrouter", ai_model="generic", OPENROUTER_MODEL="vendor/model-x")
    assert settings.ai_selected_model == "vendor/model-x"
    assert (
        make_settings(ai_provider="gemini", ai_model="gemini-2.5-pro").ai_selected_model == "gemini-2.5-pro"
    )


@pytest.mark.parametrize("selected", ["openai", "anthropic", "gemini", "openrouter", "ollama"])
def test_a_provider_never_receives_another_providers_key(selected: str) -> None:
    others = {variable: value for name, (variable, value) in KEYS.items() if name != selected}
    settings = make_settings(ai_provider=selected, ai_model="m", **others)
    assert settings.ai_credential is None
    if selected in KEYS:
        assert not create_provider(settings).status().configured


def test_the_generic_key_is_used_for_whichever_provider_is_selected() -> None:
    settings = make_settings(ai_provider="gemini", ai_model="m", ai_api_key="generic-key")
    credential = settings.ai_credential
    assert credential is not None
    assert credential.get_secret_value() == "generic-key"


@pytest.mark.parametrize("model", ["gpt 5", "model;rm -rf", "../etc/passwd", "-flag", "x" * 201])
def test_invalid_model_names_are_refused(model: str) -> None:
    with pytest.raises(ValidationError, match="AI model names"):
        make_settings(ai_provider="openai", ai_model=model)


def test_model_allowlist() -> None:
    allowed = "gpt-5, gemini-2.5-pro ,vendor/model-x"
    settings = make_settings(
        ai_enabled=True, ai_provider="openai", ai_model="gpt-5", ai_allowed_models=allowed
    )
    assert settings.ai_allowed_models == ["gpt-5", "gemini-2.5-pro", "vendor/model-x"]
    with pytest.raises(ValidationError, match="CODEWALK_AI_ALLOWED_MODELS"):
        make_settings(ai_enabled=True, ai_provider="openai", ai_model="gpt-4o", ai_allowed_models=allowed)
    with pytest.raises(ValidationError, match="CODEWALK_AI_ALLOWED_MODELS"):  # the provider-specific model
        make_settings(
            ai_enabled=True,
            ai_provider="openrouter",
            OPENROUTER_MODEL="other/model",
            ai_allowed_models=allowed,
        )
    # Not enforced while AI is off, so an allowlist can be prepared before switching models.
    make_settings(ai_enabled=False, ai_provider="openai", ai_model="gpt-4o", ai_allowed_models=allowed)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"OPENROUTER_BASE_URL": "http://openrouter.example/api/v1"}, "OPENROUTER_BASE_URL"),
        ({"OPENROUTER_BASE_URL": "https://user:pw@openrouter.example/api/v1"}, "OPENROUTER_BASE_URL"),
        ({"OLLAMA_BASE_URL": "ftp://ollama.local"}, "OLLAMA_BASE_URL"),
        ({"OLLAMA_BASE_URL": "http://admin:pw@ollama.local:11434"}, "OLLAMA_BASE_URL"),
    ],
)
def test_provider_urls_are_validated(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_settings(**env)


def test_production_ollama_must_be_local_or_https() -> None:
    production = {"env": "production", "secret_key": "k" * 48, "cors_origins": []}
    with pytest.raises(ValidationError, match="OLLAMA_BASE_URL must use https"):
        make_settings(OLLAMA_BASE_URL="http://ollama.internal:11434", **production)
    make_settings(OLLAMA_BASE_URL="http://localhost:11434", **production)
    make_settings(OLLAMA_BASE_URL="https://ollama.internal", **production)
    make_settings(OLLAMA_BASE_URL="http://ollama:11434")  # a compose service in development


# --- the request each provider sends --------------------------------------------------------------


def test_openai_request_is_unchanged() -> None:
    seen, handler = capture()
    provider(OPENAI, handler).generate_structured(REQUEST)
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer test-key"
    assert seen["body"]["max_completion_tokens"] == 1000
    assert "max_tokens" not in seen["body"]
    assert "usage" not in seen["body"]
    assert seen["body"]["response_format"]["type"] == "json_schema"


def test_gemini_request() -> None:
    seen, handler = capture()
    result = provider(GEMINI, handler).generate_structured(REQUEST)
    assert seen["url"] == f"{GEMINI_BASE_URL}/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer test-key"
    assert seen["body"]["max_tokens"] == 1000
    assert "max_completion_tokens" not in seen["body"]
    assert seen["body"]["model"] == "test-model"
    assert result.data == {"answer": "ok"}
    assert result.usage == {"input_tokens": 20, "output_tokens": 5}


def test_openrouter_request_and_cost_accounting() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion({"answer": "ok"}, cost=0.001234))

    result = provider(OPENROUTER, handler).generate_structured(REQUEST)
    assert seen["url"] == f"{OPENROUTER_BASE_URL}/chat/completions"
    assert seen["body"]["usage"] == {"include": True}
    assert seen["body"]["max_tokens"] == 1000
    assert result.usage == {"input_tokens": 20, "output_tokens": 5, "cost_microusd": 1234}
    assert result.request_id == "gen-1"


@pytest.mark.parametrize(
    "base", ["http://localhost:11434", "http://localhost:11434/", "http://localhost:11434/v1"]
)
def test_ollama_request_has_no_credential(base: str) -> None:
    seen, handler = capture()
    provider(OLLAMA, handler, api_key=None, base_url=base).generate_structured(REQUEST)
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in seen["headers"]
    assert seen["body"]["max_tokens"] == 1000


# --- normalized failures -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("profile", "response", "error", "message"),
    [
        (
            GEMINI,
            httpx.Response(400, json={"error": {"details": [{"reason": "API_KEY_INVALID"}]}}),
            AIProviderError,
            "authentication failed",
        ),
        (
            GEMINI,
            httpx.Response(400, json={"error": {"message": "bad schema"}}),
            AIProviderError,
            "rejected the request",
        ),
        (
            GEMINI,
            httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}),
            AIRateLimitedError,
            "rate limiting",
        ),
        (OPENROUTER, httpx.Response(402, json={"error": {"code": 402}}), AIProviderError, "no credit"),
        (
            OPENROUTER,
            httpx.Response(200, json={"error": {"code": 502, "message": "upstream"}}),
            AIUnavailableError,
            "unavailable",
        ),
        (
            OPENROUTER,
            httpx.Response(200, json={"error": {"code": 429, "message": "slow down"}}),
            AIRateLimitedError,
            "rate limiting",
        ),
        (
            OPENROUTER,
            httpx.Response(200, json={"choices": [{"message": {"content": ""}, "finish_reason": "error"}]}),
            AIUnavailableError,
            "failed while answering",
        ),
        (
            OLLAMA,
            httpx.Response(404, json={"error": "model 'x' not found, try pulling it first"}),
            AIProviderError,
            "not available",
        ),
        (
            OLLAMA,
            httpx.Response(500, json={"error": "out of memory"}),
            AIUnavailableError,
            "temporarily unavailable",
        ),
        (
            OPENAI,
            httpx.Response(200, content=b"<html>gateway</html>"),
            AIMalformedResponseError,
            "could not be used",
        ),
        (
            GEMINI,
            httpx.Response(200, json=completion(["not", "an", "object"])),
            AIMalformedResponseError,
            "could not be used",
        ),
        (OPENROUTER, httpx.Response(413, json={}), AIContextTooLargeError, "too large"),
    ],
)
def test_provider_failures_are_normalized(
    profile: CompatibleProfile, response: httpx.Response, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        provider(profile, lambda _: response).generate_structured(REQUEST)


@pytest.mark.parametrize(
    ("profile", "response", "code"),
    [
        # What OpenAI answered for an account without credit (observed 2026-10-05): a 429 that is not
        # a rate limit, so "try again shortly" would be wrong.
        (
            OPENAI,
            httpx.Response(
                429, json={"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota"}}
            ),
            "ai_quota_exceeded",
        ),
        (OPENAI, httpx.Response(429, json={"error": {"code": "insufficient_quota"}}), "ai_quota_exceeded"),
        (OPENROUTER, httpx.Response(402, json={"error": {"code": 402}}), "ai_quota_exceeded"),
        (OPENAI, httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}}), "ai_rate_limited"),
        (OPENAI, httpx.Response(401, json={"error": {"code": "invalid_api_key"}}), "ai_auth_failed"),
        (OPENAI, httpx.Response(403, json={}), "ai_auth_failed"),
        (
            GEMINI,
            httpx.Response(400, json={"error": {"details": [{"reason": "API_KEY_INVALID"}]}}),
            "ai_auth_failed",
        ),
        (OPENAI, httpx.Response(404, json={"error": {"code": "model_not_found"}}), "ai_model_unavailable"),
    ],
)
def test_failures_carry_a_specific_reason_code(
    profile: CompatibleProfile, response: httpx.Response, code: str
) -> None:
    with pytest.raises(AIError) as raised:
        provider(profile, lambda _: response).generate_structured(REQUEST)
    assert raised.value.code == code
    if code == "ai_quota_exceeded":
        assert "no credit or quota" in raised.value.message
        assert "try again shortly" not in raised.value.message.lower()


def test_unreachable_provider_logs_the_network_error_type(caplog: pytest.LogCaptureFixture) -> None:
    def reset(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection reset by peer", request=request)

    with caplog.at_level(logging.WARNING), pytest.raises(AIUnavailableError, match="network error"):
        provider(OPENAI, reset).generate_structured(REQUEST)
    assert "could not be reached (ReadError)" in caplog.text


@pytest.mark.parametrize("profile", [OPENAI, GEMINI, OPENROUTER, OLLAMA])
def test_timeouts_and_unreachable_servers(profile: CompatibleProfile) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AITimeoutError):
        provider(profile, timeout).generate_structured(REQUEST)
    with pytest.raises(AIUnavailableError, match="could not be reached"):
        provider(profile, refused).generate_structured(REQUEST)


# --- limits, no fallback, and secrets -------------------------------------------------------------


def test_oversized_prompts_fail_before_any_provider_call() -> None:
    stub = StubProvider()
    service = AIService(make_settings(ai_enabled=True, ai_max_input_chars=10_000), provider=stub)
    with pytest.raises(AIContextTooLargeError, match="10000 character"):
        service.run(stub, "system", "x" * 10_001, ModelExplanation)
    assert stub.requests == []


def test_a_failing_provider_is_not_replaced_by_another() -> None:
    """Gemini is configured too, but only the selected OpenAI provider is ever built or called."""
    calls: list[str] = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503, json={})

    settings = make_settings(
        ai_enabled=True, ai_provider="openai", ai_model="m", OPENAI_API_KEY="k", GEMINI_API_KEY="g"
    )
    service = AIService(settings)
    assert service.provider is not None
    assert service.provider.name == "openai"
    service.provider = provider(OPENAI, down)
    with pytest.raises(AIUnavailableError):
        service.run(service.provider, "s", "u", ModelExplanation)
    assert calls == ["https://api.openai.com/v1/chat/completions"]


@pytest.mark.parametrize("name", ["openai", "gemini", "openrouter"])
def test_keys_never_reach_status_errors_or_logs(name: str, caplog: pytest.LogCaptureFixture) -> None:
    variable, secret = KEYS[name]
    settings = make_settings(ai_enabled=True, ai_provider=name, ai_model="m", **{variable: secret})
    service = AIService(settings)
    assert service.provider is not None
    rejected = OpenAICompatibleProvider(
        api_key=secret,
        model="m",
        transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"error": {"message": secret}})),
        profile={"openai": OPENAI, "gemini": GEMINI, "openrouter": OPENROUTER}[name],
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(AIProviderError) as raised:
        rejected.generate_structured(REQUEST)
    seen = " ".join(
        [str(raised.value), repr(settings), json.dumps(service.status().model_dump()), caplog.text]
    )
    assert secret not in seen


def test_rag_embeddings_stay_independent_of_the_llm_provider() -> None:
    settings = make_settings(
        ai_enabled=True,
        ai_provider="gemini",
        ai_model="m",
        GEMINI_API_KEY="g",
        rag_enabled=True,
        voyage_api_key="voyage-test-key",
    )
    embedding = create_embedding_provider(settings)
    assert embedding.name == "voyage"
    assert embedding.status().configured
    ai = settings.ai_credential
    assert ai is not None
    assert ai.get_secret_value() == "g"  # the Voyage key is never the AI key
    assert (
        not create_provider(make_settings(ai_provider="gemini", ai_model="m", voyage_api_key="v"))
        .status()
        .configured
    )
