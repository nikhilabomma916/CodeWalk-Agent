"""Provider registry. Add a provider by implementing ``AIProvider`` and registering it here.

Exactly one provider is used: the one named by CODEWALK_AI_PROVIDER. There is no fallback to another
provider when it fails or is not configured, and a provider only ever receives its own credential.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import AI_PROVIDERS, Settings
from app.services.ai.base import AIProvider
from app.services.ai.providers.anthropic import AnthropicProvider
from app.services.ai.providers.openai_compatible import (
    GEMINI,
    OLLAMA,
    OPENAI,
    OPENROUTER,
    CompatibleProfile,
    OpenAICompatibleProvider,
)

DEFAULT_PROVIDER = "anthropic"


def _anthropic(settings: Settings) -> AIProvider:
    credential = settings.ai_credential
    return AnthropicProvider(
        api_key=credential.get_secret_value() if credential else None,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
    )


def _compatible(
    profile: CompatibleProfile, base_url: Callable[[Settings], str | None]
) -> Callable[[Settings], AIProvider]:
    def build(settings: Settings) -> AIProvider:
        credential = settings.ai_credential
        return OpenAICompatibleProvider(
            api_key=credential.get_secret_value() if credential else None,
            model=settings.ai_selected_model,
            base_url=base_url(settings),
            timeout_seconds=settings.ai_timeout_seconds,
            profile=profile,
        )

    return build


# Provider-specific code stays in its module; everything else talks to the AIProvider protocol.
PROVIDERS: dict[str, Callable[[Settings], AIProvider]] = {
    "anthropic": _anthropic,
    "openai": _compatible(OPENAI, lambda s: s.ai_base_url),
    "gemini": _compatible(GEMINI, lambda s: None),  # Google's fixed endpoint
    "openrouter": _compatible(OPENROUTER, lambda s: s.openrouter_base_url),
    "ollama": _compatible(OLLAMA, lambda s: s.ollama_base_url),
}
if tuple(PROVIDERS) != AI_PROVIDERS:  # the settings and the registry name the same providers
    raise RuntimeError("AI provider registry and AI_PROVIDERS differ")


class UnknownProviderError(ValueError):
    pass


def create_provider(settings: Settings) -> AIProvider:
    name = settings.ai_provider_name
    factory = PROVIDERS.get(name)
    if factory is None:
        raise UnknownProviderError(name)
    return factory(settings)
