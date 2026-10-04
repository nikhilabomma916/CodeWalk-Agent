"""OpenAI-compatible Chat Completions provider (Module 17, EXPERIMENTAL).

Selected with ``CODEWALK_AI_PROVIDER=openai``. Speaks the Chat Completions API (``POST
{base_url}/chat/completions``) with a JSON-schema ``response_format``, so it also serves compatible
servers through ``CODEWALK_AI_BASE_URL``. The answer is validated again by the caller.

- No model is assumed: ``CODEWALK_AI_MODEL`` must be set, otherwise the provider reports itself as not
  configured.
- The credential (``CODEWALK_AI_API_KEY`` or ``OPENAI_API_KEY``) is sent only as a bearer header; it is
  never logged or returned.
- Tested against a mock transport only: no credential was available to exercise a live API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

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

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        base_url: str | None = None,
        timeout_seconds: float = 90.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model or ""
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client: httpx.Client | None = None
        if api_key and model:
            self._client = httpx.Client(
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=timeout_seconds,
                transport=transport,
            )
        self._missing = "a credential (CODEWALK_AI_API_KEY or OPENAI_API_KEY)" if not api_key else None
        if not model:
            self._missing = "CODEWALK_AI_MODEL" if api_key else f"{self._missing} and CODEWALK_AI_MODEL"

    def status(self) -> ProviderStatus:
        if self._client is None:
            return ProviderStatus(
                provider=self.name,
                model=self.model or "(not set)",
                configured=False,
                detail=f"Set {self._missing} on the server.",
            )
        return ProviderStatus(provider=self.name, model=self.model, configured=True)

    def generate_structured(self, request: StructuredRequest) -> StructuredResult:
        client = self._client
        if client is None:
            raise AIProviderError("The AI provider is not configured.", code="ai_not_configured")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "max_completion_tokens": request.max_tokens,
            # strict mode would reject schemas with optional fields; the caller validates the answer.
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "codewalk_output", "schema": request.schema, "strict": False},
            },
        }
        try:
            response = client.post(
                f"{self.base_url}/chat/completions", json=payload, timeout=request.timeout_seconds
            )
        except httpx.TimeoutException:
            raise AITimeoutError() from None
        except httpx.HTTPError:
            raise AIUnavailableError("The AI provider could not be reached.") from None

        status = response.status_code
        request_id = response.headers.get("x-request-id")
        if status == 429:
            if _is_quota_exhausted(response):
                # Not a temporary limit: the account has no credit left, so retrying cannot help.
                logger.warning(
                    "The OpenAI-compatible provider reports no remaining quota for the configured key"
                )
                raise AIProviderError(
                    "The AI provider account has no remaining credit or quota. Add credit or billing for the "
                    "server's API key; retrying will not help."
                )
            raise AIRateLimitedError("The AI provider is rate limiting requests. Try again shortly.")
        if status in (401, 403):
            logger.warning("The OpenAI-compatible provider rejected the configured credential (%s)", status)
            raise AIProviderError("The AI provider rejected the server's credential.")
        if status == 404:
            raise AIProviderError(f"The AI model {self.model!r} is not available to this account.")
        if status == 413:
            raise AIContextTooLargeError("The request is too large for the AI provider.")
        if status >= 500:
            logger.warning("OpenAI-compatible provider error: status %s (request %s)", status, request_id)
            raise AIUnavailableError("The AI provider is temporarily unavailable.")
        if status >= 400:
            logger.warning("OpenAI-compatible provider rejected the request: status %s", status)
            raise AIProviderError("The AI provider rejected the request.")
        return self._parse(response, request_id)

    def _parse(self, response: httpx.Response, request_id: str | None) -> StructuredResult:
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise AIMalformedResponseError() from None
        if message.get("refusal"):
            raise AIRefusedError()
        if choice.get("finish_reason") == "length":
            raise AIMalformedResponseError("The AI answer was cut off before it was complete.")
        content = message.get("content")
        if not isinstance(content, str):
            raise AIMalformedResponseError()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("OpenAI-compatible provider returned non-JSON output (request %s)", request_id)
            raise AIMalformedResponseError() from None
        if not isinstance(parsed, dict):
            raise AIMalformedResponseError()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return StructuredResult(
            data=parsed,
            model=str(data.get("model") or self.model),
            request_id=request_id,
            usage={
                "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "output_tokens": int(usage.get("completion_tokens", 0) or 0),
            },
        )


def _is_quota_exhausted(response: httpx.Response) -> bool:
    """OpenAI answers 429 both for rate limits and for an account without credit (insufficient_quota)."""
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        return False
    return "insufficient_quota" in {error.get("type"), error.get("code")} or error.get("code") == (
        "credit_balance_exhausted"
    )
