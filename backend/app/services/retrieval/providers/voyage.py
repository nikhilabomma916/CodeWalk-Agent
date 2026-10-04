"""Voyage AI embedding provider (``POST https://api.voyageai.com/v1/embeddings``).

- Default model ``voyage-code-4`` (code retrieval), asked for ``EMBEDDING_DIMENSIONS``
  float dimensions.
- Queries and documents use the API's ``input_type`` ("query" / "document").
- Inputs are sent in batches that stay under the per-request limits (count and an
  estimated token budget); chunks are bounded by the caller, and ``truncation`` stays on
  as a safety net.
- The credential is read from settings only; it is never logged or returned.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from app.services.retrieval.base import (
    EMBEDDING_DIMENSIONS,
    EmbeddingMalformedResponseError,
    EmbeddingProviderError,
    EmbeddingRateLimitedError,
    EmbeddingResult,
    EmbeddingStatus,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
    InputType,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.voyageai.com/v1/embeddings"
DEFAULT_MODEL = "voyage-code-4"
MAX_TEXTS_PER_REQUEST = 128
# Conservative token estimate (~3 characters per token for code) under the API's per-request limit.
MAX_ESTIMATED_TOKENS_PER_REQUEST = 100_000
CHARS_PER_TOKEN = 3


def _batches(texts: list[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    budget = 0
    for text in texts:
        cost = max(1, math.ceil(len(text) / CHARS_PER_TOKEN))
        if current and (
            len(current) >= MAX_TEXTS_PER_REQUEST or budget + cost > MAX_ESTIMATED_TOKENS_PER_REQUEST
        ):
            batches.append(current)
            current, budget = [], 0
        current.append(text)
        budget += cost
    if current:
        batches.append(current)
    return batches


class VoyageEmbeddingProvider:
    name = "voyage"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        dimensions: int = EMBEDDING_DIMENSIONS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.dimensions = dimensions
        self._client: httpx.Client | None = None
        if api_key:
            self._client = httpx.Client(
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=timeout_seconds,
                transport=transport,
            )

    def status(self) -> EmbeddingStatus:
        if self._client is None:
            return EmbeddingStatus(
                provider=self.name,
                model=self.model,
                configured=False,
                detail="No credential: set VOYAGE_API_KEY on the server.",
            )
        return EmbeddingStatus(provider=self.name, model=self.model, configured=True)

    def close(self) -> None:
        """Releases the HTTP connection pool (the provider is unusable afterwards)."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def embed(self, texts: list[str], input_type: InputType) -> EmbeddingResult:
        client = self._client
        if client is None:
            raise EmbeddingProviderError(
                "The embedding provider has no credential configured.", code="rag_not_configured"
            )
        vectors: list[list[float]] = []
        tokens = 0
        model = self.model
        for batch in _batches(texts):
            data = self._post(client, batch, input_type)
            batch_vectors, model, used = self._parse(data, len(batch))
            vectors.extend(batch_vectors)
            tokens += used
        return EmbeddingResult(vectors=vectors, model=model, total_tokens=tokens)

    def _post(self, client: httpx.Client, batch: list[str], input_type: InputType) -> Any:
        payload = {
            "input": batch,
            "model": self.model,
            "input_type": input_type.value,
            "output_dimension": self.dimensions,
            "output_dtype": "float",
            "truncation": True,
        }
        try:
            response = client.post(API_URL, json=payload)
        except httpx.TimeoutException:
            raise EmbeddingTimeoutError() from None
        except httpx.HTTPError:
            raise EmbeddingUnavailableError("The embedding provider could not be reached.") from None

        status = response.status_code
        if status == 429:
            raise EmbeddingRateLimitedError(
                "The embedding provider is rate limiting requests. Try again shortly."
            )
        if status in (401, 403):
            logger.warning("Voyage AI rejected the configured credential (status %s)", status)
            raise EmbeddingProviderError("The embedding provider rejected the server's credential.")
        if status >= 500:
            logger.warning("Voyage AI server error: status %s", status)
            raise EmbeddingUnavailableError("The embedding provider is temporarily unavailable.")
        if status >= 400:
            logger.warning("Voyage AI rejected the request: status %s", status)
            raise EmbeddingProviderError(
                f"The embedding provider rejected the request (model {self.model!r})."
            )
        try:
            return response.json()
        except ValueError:
            raise EmbeddingMalformedResponseError() from None

    def _parse(self, data: Any, expected: int) -> tuple[list[list[float]], str, int]:
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != expected:
            raise EmbeddingMalformedResponseError(
                "The embedding provider returned the wrong number of vectors."
            )
        ordered: list[list[float] | None] = [None] * expected
        for item in items:
            index = item.get("index") if isinstance(item, dict) else None
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(index, int) or not 0 <= index < expected or ordered[index] is not None:
                raise EmbeddingMalformedResponseError()
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise EmbeddingMalformedResponseError(
                    f"The embedding provider returned vectors that are not {self.dimensions}-dimensional."
                )
            try:
                values = [float(value) for value in vector]
            except (TypeError, ValueError):
                raise EmbeddingMalformedResponseError() from None
            if not all(math.isfinite(value) for value in values):
                raise EmbeddingMalformedResponseError()
            ordered[index] = values
        usage = data.get("usage")
        tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
        model = data.get("model") if isinstance(data.get("model"), str) else self.model
        return [v for v in ordered if v is not None], model, tokens if isinstance(tokens, int) else 0
