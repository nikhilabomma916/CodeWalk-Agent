"""A controlled EmbeddingProvider for tests. NOT a real embedding model and NOT Voyage AI.

Vectors are a hashed bag of identifier tokens (``authenticateUser`` -> authenticate,
user), L2-normalised, so texts that share words point in similar directions. That
is enough to test CodeWalk's own behavior (chunking, storage, incremental indexing,
pgvector queries, filters, fusion, context, authorization) deterministically and
offline. It says nothing about retrieval quality or whether the Voyage integration
works; that is covered by the provider tests (mock transport) and the optional live
smoke test (tests/test_live_voyage.py).
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

from app.services.retrieval.base import (
    EMBEDDING_DIMENSIONS,
    EmbeddingResult,
    EmbeddingStatus,
    InputType,
    RetrievalError,
)

_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text) if len(w) > 1]


def stub_vector(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in tokens(text):
        slot = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % EMBEDDING_DIMENSIONS
        vector[slot] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [v / norm for v in vector]


@dataclass
class StubEmbeddingProvider:
    name: str = "stub-embeddings"
    model: str = "stub-hashed-bag-of-words"
    dimensions: int = EMBEDDING_DIMENSIONS
    configured: bool = True
    # Raised (in order) instead of answering, one per embed() call.
    errors: list[RetrievalError] = field(default_factory=list)
    calls: list[tuple[InputType, list[str]]] = field(default_factory=list)

    def status(self) -> EmbeddingStatus:
        return EmbeddingStatus(
            provider=self.name,
            model=self.model,
            configured=self.configured,
            detail=None if self.configured else "stub not configured",
        )

    def embed(self, texts: list[str], input_type: InputType) -> EmbeddingResult:
        self.calls.append((input_type, list(texts)))
        if self.errors:
            raise self.errors.pop(0)
        return EmbeddingResult(
            vectors=[stub_vector(t) for t in texts],
            model=self.model,
            total_tokens=sum(len(tokens(t)) for t in texts),
        )

    def texts(self, input_type: InputType) -> list[str]:
        return [t for kind, batch in self.calls if kind is input_type for t in batch]
