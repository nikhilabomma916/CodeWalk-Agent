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

from app.core.exceptions import error_response
from app.core.logging import request_id_var

logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.errors")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class RequestContextMiddleware:
    """Assigns a request id, adds security headers, logs access, and converts
    unhandled exceptions into a generic 500 ErrorResponse.

    Handling the 500 here (instead of only in Starlette's outermost
    ServerErrorMiddleware) means the response still passes through CORS
    middleware, so browsers can read it, and still carries the request id.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

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
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s -> %d (%.1f ms)",
                scope.get("method"),
                scope.get("path"),
                status_code,
                duration_ms,
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
