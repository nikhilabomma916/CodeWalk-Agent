"""Provider registry. Add a provider by implementing ``AIProvider`` and registering it here."""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import Settings
from app.services.ai.base import AIProvider
from app.services.ai.providers.anthropic import AnthropicProvider
from app.services.ai.providers.openai_compatible import OpenAICompatibleProvider

DEFAULT_PROVIDER = "anthropic"


def _anthropic(settings: Settings) -> AIProvider:
    credential = settings.ai_credential
    return AnthropicProvider(
        api_key=credential.get_secret_value() if credential else None,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
    )


def _openai(settings: Settings) -> AIProvider:
    credential = settings.ai_credential
    return OpenAICompatibleProvider(
        api_key=credential.get_secret_value() if credential else None,
        model=settings.ai_model,
        base_url=settings.ai_base_url,
        timeout_seconds=settings.ai_timeout_seconds,
    )


# Provider-specific code stays in its module; everything else talks to the AIProvider protocol.
PROVIDERS: dict[str, Callable[[Settings], AIProvider]] = {"anthropic": _anthropic, "openai": _openai}


class UnknownProviderError(ValueError):
    pass


def create_provider(settings: Settings) -> AIProvider:
    name = (settings.ai_provider or DEFAULT_PROVIDER).lower()
    factory = PROVIDERS.get(name)
    if factory is None:
        raise UnknownProviderError(name)
    return factory(settings)
