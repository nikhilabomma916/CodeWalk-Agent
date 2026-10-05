"""Claude (Anthropic API) provider, using the official ``anthropic`` SDK.

- Answers are constrained with structured outputs (``output_config.format``,
  a JSON schema) and validated again by the caller.
- Reasoning depth is set with ``output_config.effort``; current models think
  adaptively by default, so no ``thinking`` parameter is sent.
- On current models, ``fallbacks: "default"`` lets the API retry a
  safety-classifier decline on Anthropic's recommended fallback model.
- The credential is read from settings only; it is never logged or returned.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.services.ai.base import (
    AIContextTooLargeError,
    AIMalformedResponseError,
    AIProviderError,
    AIRateLimitedError,
    AIRefusedError,
    AITimeoutError,
    AIUnavailableError,
    ProviderStatus,
    StructuredRequest,
    StructuredResult,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
# Models that accept server-side refusal fallback ("default" routing).
_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None = None,
        timeout_seconds: float = 90.0,
        max_retries: int = 0,  # no automatic retries: the user retries (Module 23)
        http_client: anthropic.DefaultHttpxClient | None = None,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self._client: anthropic.Anthropic | None = None
        if api_key:
            self._client = anthropic.Anthropic(
                api_key=api_key,
                timeout=timeout_seconds,
                max_retries=max_retries,
                http_client=http_client,
            )

    def status(self) -> ProviderStatus:
        if self._client is None:
            return ProviderStatus(
                provider=self.name,
                model=self.model,
                configured=False,
                detail="No credential: set ANTHROPIC_API_KEY (or CODEWALK_AI_API_KEY) on the server.",
            )
        return ProviderStatus(provider=self.name, model=self.model, configured=True)

    def _params(self, request: StructuredRequest) -> dict[str, Any]:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": request.schema}}
        if "haiku" not in self.model:  # effort is not supported on Haiku models
            output_config["effort"] = request.effort
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "output_config": output_config,
            "timeout": request.timeout_seconds,
        }
        if self.model in _FALLBACK_MODELS:
            params["betas"] = [_FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def generate_structured(self, request: StructuredRequest) -> StructuredResult:
        if self._client is None:
            raise AIProviderError("The AI provider has no credential configured.", code="ai_not_configured")
        try:
            response = self._client.beta.messages.create(**self._params(request))
        except anthropic.APITimeoutError:
            raise AITimeoutError() from None
        except anthropic.RateLimitError:
            raise AIRateLimitedError(
                "The AI provider is rate limiting requests. Try again shortly."
            ) from None
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            logger.warning("Anthropic rejected the configured credential")
            raise AIProviderError("The AI provider rejected the server's credential.") from None
        except anthropic.NotFoundError:
            raise AIProviderError(f"The AI model {self.model!r} is not available to this account.") from None
        except anthropic.APIStatusError as exc:
            logger.warning("Anthropic API error: status %s (request %s)", exc.status_code, exc.request_id)
            if exc.status_code == 413:
                raise AIContextTooLargeError("The request is too large for the AI provider.") from None
            if exc.status_code >= 500:
                raise AIUnavailableError("The AI provider is temporarily unavailable.") from None
            raise AIProviderError("The AI provider rejected the request.") from None
        except anthropic.APIConnectionError:
            raise AIUnavailableError("The AI provider could not be reached.") from None

        request_id = getattr(response, "_request_id", None)
        if response.stop_reason == "refusal":
            raise AIRefusedError()
        if response.stop_reason == "max_tokens":
            raise AIMalformedResponseError("The AI answer was cut off before it was complete.")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise AIMalformedResponseError()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Anthropic returned non-JSON structured output (request %s)", request_id)
            raise AIMalformedResponseError() from None
        if not isinstance(data, dict):
            raise AIMalformedResponseError()
        usage = response.usage
        return StructuredResult(
            data=data,
            model=response.model,
            request_id=request_id,
            usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
        )
