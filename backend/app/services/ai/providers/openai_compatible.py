"""OpenAI-compatible Chat Completions providers: OpenAI (Module 17), Gemini, OpenRouter, Ollama (Module 19).

Each speaks the Chat Completions API (``POST {base_url}/chat/completions``) with a JSON-schema
``response_format``; the answer is validated again by the caller. They are not identical, so each has
a ``CompatibleProfile`` with its own endpoint, credential rules, token field and error quirks:

- OpenAI: ``max_completion_tokens``; ``CODEWALK_AI_BASE_URL`` may point at another compatible server.
- Gemini: Google's OpenAI-compatible endpoint (``/v1beta/openai``), ``max_tokens``. An invalid key is
  reported as HTTP 400 with an ``API_KEY_INVALID`` reason rather than 401.
- OpenRouter: ``max_tokens``; HTTP 402 means the account has no credit; an upstream failure can arrive
  as HTTP 200 with an ``error`` object; the cost of a request is reported in ``usage.cost``.
- Ollama: self-hosted (``{OLLAMA_BASE_URL}/v1``), no credential, ``max_tokens``; an unknown model is a
  404 ("try pulling it first"). Never required: the hosted deployment does not use it by default.

No model is assumed for any of them: without one the provider reports itself as not configured.
Credentials are sent only as a bearer header and are never logged or returned. Streaming and native
tool calling are not used: the agent asks for one structured JSON answer per step, and the server
decides and authorizes every tool call itself, so every provider supports the agent the same way.
Requests are never retried here: an AI call costs money, and the user can retry.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.ai.base import (
    QUOTA_MESSAGE,
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
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OLLAMA_BASE_URL = "http://localhost:11434"
# An unreachable server (a stopped Ollama, a wrong URL) fails quickly instead of after the full timeout.
CONNECT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class CompatibleProfile:
    name: str
    default_base_url: str
    key_hint: str  # how to configure the credential, shown when it is missing
    model_hint: str
    requires_key: bool = True
    max_tokens_field: str = "max_tokens"
    # Extra JSON fields for every request (for example OpenRouter's usage accounting).
    extra_body: tuple[tuple[str, Any], ...] = ()


OPENAI = CompatibleProfile(
    name="openai",
    default_base_url=DEFAULT_BASE_URL,
    key_hint="a credential (CODEWALK_AI_API_KEY or OPENAI_API_KEY)",
    model_hint="CODEWALK_AI_MODEL",
    max_tokens_field="max_completion_tokens",
)
GEMINI = CompatibleProfile(
    name="gemini",
    default_base_url=GEMINI_BASE_URL,
    key_hint="a credential (CODEWALK_AI_API_KEY or GEMINI_API_KEY)",
    model_hint="CODEWALK_AI_MODEL",
)
OPENROUTER = CompatibleProfile(
    name="openrouter",
    default_base_url=OPENROUTER_BASE_URL,
    key_hint="a credential (CODEWALK_AI_API_KEY or OPENROUTER_API_KEY)",
    model_hint="OPENROUTER_MODEL (or CODEWALK_AI_MODEL)",
    extra_body=(("usage", {"include": True}),),
)
OLLAMA = CompatibleProfile(
    name="ollama",
    default_base_url=OLLAMA_BASE_URL,
    key_hint="",
    model_hint="OLLAMA_MODEL (or CODEWALK_AI_MODEL)",
    requires_key=False,
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        base_url: str | None = None,
        timeout_seconds: float = 90.0,
        transport: httpx.BaseTransport | None = None,
        profile: CompatibleProfile = OPENAI,
    ) -> None:
        self.profile = profile
        self.name = profile.name
        self.model = model or ""
        base = (base_url or profile.default_base_url).rstrip("/")
        # Ollama serves its OpenAI-compatible API under /v1 of the server URL users configure.
        if profile is OLLAMA and not base.endswith("/v1"):
            base = f"{base}/v1"
        self.base_url = base
        self._client: httpx.Client | None = None
        missing = [profile.key_hint] if profile.requires_key and not api_key else []
        if not model:
            missing.append(profile.model_hint)
        self._missing = " and ".join(missing) or None
        if self._missing is None:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            self._client = httpx.Client(
                headers=headers,
                timeout=httpx.Timeout(timeout_seconds, connect=min(CONNECT_TIMEOUT_SECONDS, timeout_seconds)),
                transport=transport,
            )

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
            self.profile.max_tokens_field: request.max_tokens,
            # strict mode would reject schemas with optional fields; the caller validates the answer.
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "codewalk_output", "schema": request.schema, "strict": False},
            },
            **dict(self.profile.extra_body),
        }
        try:
            response = client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=httpx.Timeout(
                    request.timeout_seconds, connect=min(CONNECT_TIMEOUT_SECONDS, request.timeout_seconds)
                ),
            )
        except httpx.TimeoutException:
            raise AITimeoutError() from None
        except httpx.HTTPError as exc:
            # The exception type only (ConnectError, ReadError, ...): never the request or headers.
            logger.warning("The %s provider could not be reached (%s)", self.name, type(exc).__name__)
            raise AIUnavailableError("The AI provider could not be reached (network error).") from None

        status = response.status_code
        request_id = response.headers.get("x-request-id")
        if status >= 400:
            self._raise_for_status(response, request_id)
        return self._parse(response, request_id)

    def _raise_for_status(self, response: httpx.Response, request_id: str | None) -> None:
        status = response.status_code
        if status == 402 or (status == 429 and _is_quota_exhausted(response)):
            logger.warning("The %s provider account has no credit or quota left (%s)", self.name, status)
            raise AIProviderError(QUOTA_MESSAGE, code="ai_quota_exceeded")
        if status == 429:
            raise AIRateLimitedError("The AI provider is rate limiting requests. Try again shortly.")
        if status in (401, 403) or (status == 400 and _is_invalid_key(response)):
            logger.warning("The %s provider rejected the configured credential (%s)", self.name, status)
            raise AIProviderError(
                "The AI provider rejected the server's API key (authentication failed).",
                code="ai_auth_failed",
            )
        if status == 404:
            raise AIProviderError(
                f"The AI model {self.model!r} is not available to this account.", code="ai_model_unavailable"
            )
        if status == 413:
            raise AIContextTooLargeError("The request is too large for the AI provider.")
        if status >= 500:
            logger.warning("%s provider error: status %s (request %s)", self.name, status, request_id)
            raise AIUnavailableError("The AI provider is temporarily unavailable.")
        logger.warning("%s provider rejected the request: status %s", self.name, status)
        raise AIProviderError("The AI provider rejected the request.")

    def _parse(self, response: httpx.Response, request_id: str | None) -> StructuredResult:
        try:
            data = response.json()
        except ValueError:
            raise AIMalformedResponseError() from None
        if isinstance(data, dict) and isinstance(data.get("error"), dict) and not data.get("choices"):
            # OpenRouter reports some upstream failures as HTTP 200 with an error object.
            code = data["error"].get("code")
            logger.warning("%s provider returned an error object (code %s)", self.name, code)
            if code == 429:
                raise AIRateLimitedError("The AI provider is rate limiting requests. Try again shortly.")
            raise AIUnavailableError("The AI provider is temporarily unavailable.")
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise AIMalformedResponseError() from None
        if message.get("refusal"):
            raise AIRefusedError()
        if choice.get("finish_reason") == "length":
            raise AIMalformedResponseError("The AI answer was cut off before it was complete.")
        if choice.get("finish_reason") == "error" or isinstance(choice.get("error"), dict):
            raise AIUnavailableError("The AI provider failed while answering.")
        content = message.get("content")
        if not isinstance(content, str):
            raise AIMalformedResponseError()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("%s provider returned non-JSON output (request %s)", self.name, request_id)
            raise AIMalformedResponseError() from None
        if not isinstance(parsed, dict):
            raise AIMalformedResponseError()
        return StructuredResult(
            data=parsed,
            model=str(data.get("model") or self.model),
            request_id=request_id or (str(data["id"]) if isinstance(data.get("id"), str) else None),
            usage=_usage(data.get("usage")),
        )


def _usage(raw: object) -> dict[str, int]:
    usage = raw if isinstance(raw, dict) else {}
    result = {
        "input_tokens": _count(usage.get("prompt_tokens")),
        "output_tokens": _count(usage.get("completion_tokens")),
    }
    cost = usage.get("cost")  # OpenRouter: credits (US dollars) charged for the request
    if isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0:
        result["cost_microusd"] = round(cost * 1_000_000)
    return result


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


_QUOTA_CODES = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached"}


def _is_quota_exhausted(response: httpx.Response) -> bool:
    """OpenAI answers an exhausted account with HTTP 429 and code/type insufficient_quota: not a rate
    limit (retrying later does not help until credit is added)."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return False
    if not isinstance(error, dict):
        return False
    return bool({str(error.get("code")), str(error.get("type"))} & _QUOTA_CODES)


def _is_invalid_key(response: httpx.Response) -> bool:
    """Gemini answers an invalid API key with HTTP 400 and reason API_KEY_INVALID."""
    try:
        text = json.dumps(response.json())
    except ValueError:
        return False
    return "API_KEY_INVALID" in text or "API key not valid" in text
