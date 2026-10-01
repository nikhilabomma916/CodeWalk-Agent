"""Provider-independent AI contract.

Application code talks to ``AIProvider`` only. A provider turns one structured
request (system instructions, user content, a JSON schema for the answer) into
a JSON object, and maps its own failures onto the ``AIError`` hierarchy below,
so callers never see provider SDK exceptions, credentials, or raw payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.exceptions import AppError


class AIError(AppError):
    """Base class for AI failures. Messages are safe to show to API clients."""

    status_code = 502
    code = "ai_error"


class AIDisabledError(AIError):
    status_code = 503
    code = "ai_disabled"

    def __init__(self) -> None:
        super().__init__("AI assistance is turned off on this server (CODEWALK_AI_ENABLED is not true).")


class AINotConfiguredError(AIError):
    status_code = 503
    code = "ai_not_configured"


class AITimeoutError(AIError):
    status_code = 504
    code = "ai_timeout"

    def __init__(self) -> None:
        super().__init__("The AI provider did not answer in time. Try again.")


class AIRateLimitedError(AIError):
    status_code = 429
    code = "ai_rate_limited"


class AIUnavailableError(AIError):
    """Network failure or provider-side outage."""

    status_code = 503
    code = "ai_unavailable"


class AIProviderError(AIError):
    """The provider rejected the request (bad request, auth, permissions, ...)."""

    status_code = 502
    code = "ai_provider_error"


class AIContextTooLargeError(AIError):
    status_code = 413
    code = "ai_context_too_large"


class AIMalformedResponseError(AIError):
    status_code = 502
    code = "ai_malformed_response"

    def __init__(self, detail: str = "The AI provider returned an answer that could not be used.") -> None:
        super().__init__(detail)


class AIRefusedError(AIError):
    status_code = 422
    code = "ai_refused"

    def __init__(self) -> None:
        super().__init__("The AI provider declined this request.")


@dataclass(frozen=True)
class ProviderStatus:
    """Static configuration state. Computing it never calls the provider."""

    provider: str
    model: str
    configured: bool
    detail: str | None = None


@dataclass
class StructuredRequest:
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int
    timeout_seconds: float
    effort: str


@dataclass
class StructuredResult:
    data: dict[str, Any]
    model: str
    request_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class AIProvider(Protocol):
    name: str
    model: str

    def status(self) -> ProviderStatus:
        """Whether the provider can be used, without a network call."""
        ...

    def generate_structured(self, request: StructuredRequest) -> StructuredResult:
        """Run one request and return the JSON object that matches ``request.schema``.

        Raises ``AIError`` subclasses only.
        """
        ...
