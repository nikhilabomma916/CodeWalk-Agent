"""Voyage AI provider (HTTP mocked), provider registry, configuration, and RetrievalService."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.services.retrieval.base import (
    EMBEDDING_DIMENSIONS,
    EmbeddingMalformedResponseError,
    EmbeddingProviderError,
    EmbeddingRateLimitedError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
    InputType,
    RetrievalDisabledError,
    RetrievalNotConfiguredError,
)
from app.services.retrieval.providers import (
    UnknownEmbeddingProviderError,
    create_embedding_provider,
)
from app.services.retrieval.providers.voyage import (
    API_URL,
    DEFAULT_MODEL,
    MAX_TEXTS_PER_REQUEST,
    VoyageEmbeddingProvider,
)
from app.services.retrieval.service import QueryLimitError, RetrievalService
from tests.conftest import make_settings
from tests.embedding_stub import StubEmbeddingProvider

KEY = "pa-test-voyage-key-not-real"


@pytest.fixture(autouse=True)
def _no_retrieval_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's real RAG settings or key out of these tests."""
    for name in ("RAG_ENABLED", "RAG_EMBEDDING_PROVIDER", "RAG_EMBEDDING_MODEL", "VOYAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def vector(seed: float) -> list[float]:
    return [seed] * EMBEDDING_DIMENSIONS


def answer(count: int, *, order: list[int] | None = None, dims: int = EMBEDDING_DIMENSIONS) -> dict[str, Any]:
    indexes = order or list(range(count))
    return {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [float(i)] * dims, "index": i} for i in indexes],
        "model": DEFAULT_MODEL,
        "usage": {"total_tokens": 7 * count},
    }


def provider(handler: Any) -> tuple[VoyageEmbeddingProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = handler(request)
        return result

    return VoyageEmbeddingProvider(api_key=KEY, transport=httpx.MockTransport(record)), seen


def ok(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    return httpx.Response(200, json=answer(len(texts)))


# --- request and response ----------------------------------------------------------------


def test_request_shape_and_input_types() -> None:
    voyage, seen = provider(ok)
    voyage.embed(["def a(): pass", "def b(): pass"], InputType.DOCUMENT)
    voyage.embed(["where is auth"], InputType.QUERY)

    first, second = (json.loads(r.content) for r in seen)
    assert str(seen[0].url) == API_URL
    assert seen[0].headers["Authorization"] == f"Bearer {KEY}"
    assert first == {
        "input": ["def a(): pass", "def b(): pass"],
        "model": "voyage-code-4",
        "input_type": "document",
        "output_dimension": EMBEDDING_DIMENSIONS,
        "output_dtype": "float",
        "truncation": True,
    }
    assert second["input_type"] == "query"


def test_vectors_follow_input_order_and_usage_is_summed() -> None:
    def shuffled(request: httpx.Request) -> httpx.Response:
        count = len(json.loads(request.content)["input"])
        return httpx.Response(200, json=answer(count, order=list(reversed(range(count)))))

    voyage, _ = provider(shuffled)
    result = voyage.embed(["a", "b", "c"], InputType.DOCUMENT)
    assert [v[0] for v in result.vectors] == [0.0, 1.0, 2.0]
    assert result.total_tokens == 21
    assert result.model == DEFAULT_MODEL


def test_large_inputs_are_split_into_requests() -> None:
    voyage, seen = provider(ok)
    result = voyage.embed([f"text {i}" for i in range(300)], InputType.DOCUMENT)
    sizes = [len(json.loads(r.content)["input"]) for r in seen]
    assert sizes == [MAX_TEXTS_PER_REQUEST, MAX_TEXTS_PER_REQUEST, 300 - 2 * MAX_TEXTS_PER_REQUEST]
    assert len(result.vectors) == 300

    voyage, seen = provider(ok)
    voyage.embed(["x" * 200_000, "y" * 200_000], InputType.DOCUMENT)  # token budget, not count
    assert [len(json.loads(r.content)["input"]) for r in seen] == [1, 1]


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(401, json={"detail": "bad key"}), EmbeddingProviderError),
        (httpx.Response(403), EmbeddingProviderError),
        (httpx.Response(400, json={"detail": "bad model"}), EmbeddingProviderError),
        (httpx.Response(429), EmbeddingRateLimitedError),
        (httpx.Response(500), EmbeddingUnavailableError),
        (httpx.Response(503), EmbeddingUnavailableError),
        (httpx.Response(200, text="not json"), EmbeddingMalformedResponseError),
        (httpx.Response(200, json={"data": []}), EmbeddingMalformedResponseError),
        (httpx.Response(200, json=answer(1, dims=512)), EmbeddingMalformedResponseError),
        (httpx.Response(200, json=answer(1, order=[3])), EmbeddingMalformedResponseError),
        (
            httpx.Response(200, json={"data": [{"index": 0, "embedding": ["x"] * EMBEDDING_DIMENSIONS}]}),
            EmbeddingMalformedResponseError,
        ),
    ],
)
def test_provider_failures_are_normalized(response: httpx.Response, error: type[Exception]) -> None:
    voyage, _ = provider(lambda _: response)
    with pytest.raises(error) as raised:
        voyage.embed(["code"], InputType.DOCUMENT)
    assert KEY not in str(raised.value)


def test_non_finite_values_are_rejected() -> None:
    body = answer(1)
    body["data"][0]["embedding"][5] = float("nan")
    voyage, _ = provider(lambda _: httpx.Response(200, content=json.dumps(body).encode()))
    with pytest.raises(EmbeddingMalformedResponseError):
        voyage.embed(["code"], InputType.DOCUMENT)


def test_timeouts_and_network_failures() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(EmbeddingTimeoutError):
        provider(timeout)[0].embed(["x"], InputType.QUERY)
    with pytest.raises(EmbeddingUnavailableError):
        provider(offline)[0].embed(["x"], InputType.QUERY)


def test_status_needs_no_request_and_reveals_no_key() -> None:
    voyage, seen = provider(ok)
    status = voyage.status()
    assert status.configured is True
    assert status.model == "voyage-code-4"
    assert KEY not in repr(status)
    assert seen == []

    missing = VoyageEmbeddingProvider(api_key=None).status()
    assert missing.configured is False
    assert "VOYAGE_API_KEY" in (missing.detail or "")
    with pytest.raises(EmbeddingProviderError):
        VoyageEmbeddingProvider(api_key=None).embed(["x"], InputType.QUERY)


# --- configuration and registry ----------------------------------------------------------


def test_settings_read_the_documented_variable_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "voyage-code-4")
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)
    monkeypatch.setenv("CODEWALK_RAG_MAX_CHUNKS_PER_RUN", "50")
    settings = Settings(_env_file=None)
    assert settings.rag_enabled is True
    assert settings.rag_embedding_provider == "voyage"
    assert settings.rag_embedding_model == "voyage-code-4"
    assert settings.voyage_api_key is not None
    assert settings.voyage_api_key.get_secret_value() == KEY
    assert KEY not in repr(settings)
    assert settings.rag_max_chunks_per_run == 50


def test_blank_settings_mean_unset() -> None:
    settings = make_settings(voyage_api_key="", rag_embedding_model=" ", rag_embedding_provider="")
    assert settings.voyage_api_key is None
    assert settings.rag_embedding_model is None
    assert settings.rag_embedding_provider is None
    assert make_settings().rag_enabled is False


def test_registry_builds_voyage_by_default() -> None:
    created = create_embedding_provider(make_settings(rag_enabled=True, voyage_api_key=KEY))
    assert isinstance(created, VoyageEmbeddingProvider)
    assert created.model == "voyage-code-4"
    assert created.status().configured
    other = create_embedding_provider(make_settings(rag_embedding_model="voyage-code-3"))
    assert other.model == "voyage-code-3"
    with pytest.raises(UnknownEmbeddingProviderError):
        create_embedding_provider(make_settings(rag_embedding_provider="nope"))


# --- RetrievalService ----------------------------------------------------------------------


class _User:
    id = "user-1"


def test_service_disabled_by_default() -> None:
    service = RetrievalService(make_settings())
    status = service.status()
    assert (status.enabled, status.configured, status.available) == (False, False, False)
    assert "RAG_ENABLED" in (status.detail or "")
    assert status.dimensions == EMBEDDING_DIMENSIONS
    with pytest.raises(RetrievalDisabledError):
        service.require_provider()


def test_service_enabled_without_credential_or_with_unknown_provider() -> None:
    no_key = RetrievalService(make_settings(rag_enabled=True)).status()
    assert (no_key.enabled, no_key.configured, no_key.available) == (True, False, False)
    assert no_key.provider == "voyage"
    assert "VOYAGE_API_KEY" in (no_key.detail or "")

    unknown = RetrievalService(make_settings(rag_enabled=True, rag_embedding_provider="nope"))
    assert "Unknown embedding provider" in (unknown.status().detail or "")
    with pytest.raises(RetrievalNotConfiguredError):
        unknown.require_provider()


def test_service_rejects_providers_with_other_dimensions() -> None:
    service = RetrievalService(make_settings(rag_enabled=True), StubEmbeddingProvider(dimensions=512))
    assert service.status().available is False
    assert "512" in (service.status().detail or "")


def test_query_embeddings_are_cached_and_limited() -> None:
    stub = StubEmbeddingProvider()
    service = RetrievalService(make_settings(rag_enabled=True, rag_max_queries=2), stub)
    user: Any = _User()
    first = service.embed_query(user, "find the login handler")
    assert service.embed_query(user, "find the login handler") == first
    assert len(stub.calls) == 1
    assert stub.calls[0][0] is InputType.QUERY
    service.embed_query(user, "another query")
    with pytest.raises(QueryLimitError):
        service.embed_query(user, "a third query")
