"""Provider registry. Add a provider by implementing ``AIProvider`` and registering it here."""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import Settings
from app.services.ai.base import AIProvider
from app.services.ai.providers.anthropic import AnthropicProvider

DEFAULT_PROVIDER = "anthropic"


def _anthropic(settings: Settings) -> AIProvider:
    credential = settings.ai_credential
    return AnthropicProvider(
        api_key=credential.get_secret_value() if credential else None,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
    )


PROVIDERS: dict[str, Callable[[Settings], AIProvider]] = {"anthropic": _anthropic}


class UnknownProviderError(ValueError):
    pass


def create_provider(settings: Settings) -> AIProvider:
    name = (settings.ai_provider or DEFAULT_PROVIDER).lower()
    factory = PROVIDERS.get(name)
    if factory is None:
        raise UnknownProviderError(name)
    return factory(settings)
