"""Live smoke test against the real Voyage AI embeddings API.

Runs only when VOYAGE_API_KEY is present in the server environment; it is skipped
otherwise, so the normal suite never depends on (or pays for) a provider. The key
is never printed.
"""

from __future__ import annotations

import math
import os
from typing import Any

import pytest

from app.services.retrieval.base import EMBEDDING_DIMENSIONS, InputType
from app.services.retrieval.providers import create_embedding_provider
from tests.conftest import make_settings

CREDENTIAL = os.environ.get("VOYAGE_API_KEY")

pytestmark = pytest.mark.skipif(
    not CREDENTIAL, reason="Live embedding provider test not executed: VOYAGE_API_KEY is not configured"
)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_live_code_embeddings() -> None:
    provider = create_embedding_provider(make_settings(rag_enabled=True, voyage_api_key=CREDENTIAL))
    assert provider.status().configured
    try:
        _check_embeddings(provider)
    finally:
        close = getattr(provider, "close", None)
        if close is not None:
            close()  # release the connection pool (an unclosed socket fails the run under -W error)


def _check_embeddings(provider: Any) -> None:
    documents = provider.embed(
        [
            "def add_numbers(values):\n    return sum(values)\n",
            "def reverse_text(text):\n    return text[::-1]\n",
        ],
        InputType.DOCUMENT,
    )
    query = provider.embed(["function that adds up a list of numbers"], InputType.QUERY)
    assert len(documents.vectors) == 2
    assert len(query.vectors) == 1
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in documents.vectors + query.vectors)
    assert documents.total_tokens > 0
    adds, reverses = (cosine(query.vectors[0], d) for d in documents.vectors)
    assert adds > reverses
