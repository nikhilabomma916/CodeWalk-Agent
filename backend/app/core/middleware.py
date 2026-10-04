"""Pure-ASGI middleware: request context, access logging, body size limits.

Pure ASGI (rather than ``BaseHTTPMiddleware``) keeps streaming responses and
contextvars working correctly and adds negligible overhead.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.audit import audit
from app.core.exceptions import error_response
from app.core.logging import request_id_var
from app.core.metrics import METRICS

logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.errors")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# API responses are JSON: nothing in them may load or run anything, or be framed.
API_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
# The interactive docs pages load their own scripts and styles; they keep the browser default.
_DOCS_PATHS = ("/docs", "/redoc")
HSTS_VALUE = "max-age=31536000; includeSubDomains"
_METRIC_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


def route_label(scope: Scope, api_prefix: str) -> str:
    """The matched route's template (e.g. ``/api/v1/projects/{project_id}``), never the raw path:
    metric labels stay bounded and carry no ids."""
    template = getattr(scope.get("route"), "path", None)
    if not isinstance(template, str):
        return "unmatched"
    # FastAPI reports routes of an included router relative to the include's prefix.
    if scope.get("path", "").startswith(api_prefix) and not template.startswith(api_prefix):
        template = api_prefix + template
    return template


class RequestContextMiddleware:
    """Assigns a request id, adds security headers, logs access, and converts
    unhandled exceptions into a generic 500 ErrorResponse.

    Handling the 500 here (instead of only in Starlette's outermost
    ServerErrorMiddleware) means the response still passes through CORS
    middleware, so browsers can read it, and still carries the request id.
    """

    def __init__(self, app: ASGIApp, *, api_prefix: str = "/api", hsts: bool = False) -> None:
        self.app = app
        self.api_prefix = api_prefix
        # Strict-Transport-Security only when served over HTTPS (production); never in development.
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        is_api = path.startswith(self.api_prefix)
        is_docs = path.startswith(_DOCS_PATHS)
        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", API_CONTENT_SECURITY_POLICY)
                if is_api:
                    # Responses carry one user's data: never store them in shared or browser caches.
                    headers.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            error_logger.exception(
                "Unhandled error while processing %s %s", scope.get("method"), scope.get("path")
            )
            if response_started:
                raise
            response = error_response(500, "internal_error", "An unexpected error occurred.")
            await response(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - started
            logger.info(
                "%s %s -> %d (%.1f ms)",
                scope.get("method"),
                scope.get("path"),
                status_code,
                duration * 1000,
            )
            method = scope.get("method", "")
            METRICS.observe_request(
                method if method in _METRIC_METHODS else "OTHER",
                route_label(scope, self.api_prefix),
                status_code,
                duration,
            )
            request_id_var.reset(token)


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than ``max_body_bytes`` with a 413.

    Declared ``Content-Length`` values are rejected before the body is read;
    chunked bodies are counted as they stream in.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                response = error_response(400, "bad_request", "Invalid Content-Length header.")
                await response(scope, receive, send)
                return
            if declared_size > self.max_body_bytes:
                await self._reject(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    # FastAPI re-raises HTTPException from body parsing, so this
                    # reaches the standard handler and becomes an ErrorResponse.
                    raise HTTPException(status_code=413, detail=self._message())
            return message

        await self.app(scope, limited_receive, send)

    def _message(self) -> str:
        return f"Request body exceeds the {self.max_body_bytes} byte limit."

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = error_response(413, "payload_too_large", self._message())
        await response(scope, receive, send)


class OriginCheckMiddleware:
    """CSRF defence for cookie-authenticated requests.

    Browsers send an ``Origin`` header with every cross-origin request and with
    same-origin non-GET requests. State-changing requests (POST, PUT, PATCH,
    DELETE) that carry an ``Origin`` must come from an allowed frontend origin or
    from the API's own origin; anything else is rejected with 403 before it
    reaches a route. Requests without ``Origin`` (curl, server-to-server) cannot
    ride a victim's browser cookies and are let through. Together with the
    ``SameSite=Lax`` session cookie this blocks cross-site form posts and fetches.
    """

    UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in self.UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            own_origin = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
            if origin != own_origin:
                audit(
                    "origin_rejected", level=logging.WARNING, method=scope["method"], path=scope.get("path")
                )
                response = error_response(
                    403, "origin_not_allowed", "Requests from this origin are not allowed."
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
