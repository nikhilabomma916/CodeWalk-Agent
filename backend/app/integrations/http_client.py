"""Resilient JSON-over-HTTP client for external services (AI providers, etc.).

Every transport failure is mapped to a typed ``ExternalServiceError`` so that
callers can degrade gracefully instead of crashing the request or the app.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


class ExternalServiceError(Exception):
    """Base error for a failed call to an external service.

    ``str(error)`` is client-safe: it names the service and the failure kind,
    never credentials, headers, or response bodies.
    """

    def __init__(self, service: str, message: str) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service


class ExternalServiceTimeoutError(ExternalServiceError):
    pass


class ExternalServiceUnavailableError(ExternalServiceError):
    """Connection refused, DNS failure, or other network-level error."""


class ExternalServiceHTTPError(ExternalServiceError):
    def __init__(self, service: str, status_code: int) -> None:
        super().__init__(service, f"responded with HTTP {status_code}")
        self.status_code = status_code


class ExternalServiceBadResponseError(ExternalServiceError):
    """Response body was not valid JSON or did not match the expected schema."""


class ExternalHTTPClient:
    def __init__(
        self,
        service: str,
        *,
        base_url: str,
        timeout_seconds: float,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.service = service
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers=headers,
            transport=transport,
        )

    async def request_json(
        self,
        method: str,
        path: str,
        response_model: type[ModelT],
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
    ) -> ModelT:
        try:
            response = await self._client.request(method, path, json=json, params=params)
        except httpx.TimeoutException as exc:
            raise ExternalServiceTimeoutError(self.service, "request timed out") from exc
        except httpx.TransportError as exc:
            raise ExternalServiceUnavailableError(self.service, "service is unreachable") from exc

        if response.is_error:
            logger.warning("%s returned HTTP %d for %s %s", self.service, response.status_code, method, path)
            raise ExternalServiceHTTPError(self.service, response.status_code)

        try:
            return response_model.model_validate_json(response.content)
        except ValidationError as exc:
            raise ExternalServiceBadResponseError(
                self.service, "response did not match the expected format"
            ) from exc

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ExternalHTTPClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
