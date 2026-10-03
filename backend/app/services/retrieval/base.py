"""Provider-independent embedding contract (Module 10).

Application code talks to ``EmbeddingProvider`` only. A provider turns a batch of
texts into vectors for one ``InputType`` (queries and documents are embedded
differently by retrieval models) and maps its own failures onto the
``RetrievalError`` hierarchy below, so callers never see SDK exceptions,
credentials, or raw payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.exceptions import AppError

# Width of the stored vectors (``code_chunks.embedding``). Providers are asked for exactly this
# many dimensions; changing it needs a migration and a re-index.
EMBEDDING_DIMENSIONS = 1024


class InputType(StrEnum):
    QUERY = "query"
    DOCUMENT = "document"


class RetrievalError(AppError):
    """Base class for semantic-retrieval failures. Messages are safe to show to API clients."""

    status_code = 502
    code = "rag_error"


class RetrievalDisabledError(RetrievalError):
    status_code = 503
    code = "rag_disabled"

    def __init__(self) -> None:
        super().__init__("Semantic retrieval is turned off on this server (RAG_ENABLED is not true).")


class RetrievalNotConfiguredError(RetrievalError):
    status_code = 503
    code = "rag_not_configured"


class EmbeddingTimeoutError(RetrievalError):
    status_code = 504
    code = "rag_timeout"

    def __init__(self) -> None:
        super().__init__("The embedding provider did not answer in time. Try again.")


class EmbeddingRateLimitedError(RetrievalError):
    status_code = 429
    code = "rag_rate_limited"


class EmbeddingUnavailableError(RetrievalError):
    """Network failure or provider-side outage."""

    status_code = 503
    code = "rag_unavailable"


class EmbeddingProviderError(RetrievalError):
    """The provider rejected the request (bad request, auth, unknown model, ...)."""

    status_code = 502
    code = "rag_provider_error"


class EmbeddingMalformedResponseError(RetrievalError):
    status_code = 502
    code = "rag_malformed_response"

    def __init__(
        self, detail: str = "The embedding provider returned an answer that could not be used."
    ) -> None:
        super().__init__(detail)


@dataclass(frozen=True)
class EmbeddingStatus:
    """Static configuration state. Computing it never calls the provider."""

    provider: str
    model: str
    configured: bool
    detail: str | None = None


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    total_tokens: int = 0


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def status(self) -> EmbeddingStatus:
        """Whether the provider can be used, without a network call."""
        ...

    def embed(self, texts: list[str], input_type: InputType) -> EmbeddingResult:
        """One vector of ``dimensions`` floats per text, in input order.

        Raises ``RetrievalError`` subclasses only.
        """
        ...
