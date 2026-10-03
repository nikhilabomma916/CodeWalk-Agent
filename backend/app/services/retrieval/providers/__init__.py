"""Embedding provider registry.

Add a provider by implementing ``EmbeddingProvider`` and registering it here.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import Settings
from app.services.retrieval.base import EmbeddingProvider
from app.services.retrieval.providers.voyage import VoyageEmbeddingProvider

DEFAULT_PROVIDER = "voyage"


def _voyage(settings: Settings) -> EmbeddingProvider:
    credential = settings.voyage_api_key
    return VoyageEmbeddingProvider(
        api_key=credential.get_secret_value() if credential else None,
        model=settings.rag_embedding_model,
        timeout_seconds=settings.rag_timeout_seconds,
    )


PROVIDERS: dict[str, Callable[[Settings], EmbeddingProvider]] = {"voyage": _voyage}


class UnknownEmbeddingProviderError(ValueError):
    pass


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    name = (settings.rag_embedding_provider or DEFAULT_PROVIDER).lower()
    factory = PROVIDERS.get(name)
    if factory is None:
        raise UnknownEmbeddingProviderError(name)
    return factory(settings)
