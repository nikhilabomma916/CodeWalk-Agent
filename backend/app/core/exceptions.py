"""Application exceptions and the handlers that turn them into ErrorResponse JSON.

Handlers never leak stack traces, filesystem paths, or submitted input values;
unexpected errors are logged server-side and reported generically.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var
from app.schemas.errors import ErrorBody, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors raised deliberately by services.

    ``message`` must be safe to show to API clients.
    """

    status_code: int = 400
    code: str = "bad_request"
    # Extra response headers, e.g. Retry-After.
    headers: dict[str, str] | None = None

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnsafePathError(AppError):
    status_code = 400
    code = "unsafe_path"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


class DatabaseNotConfiguredError(ServiceUnavailableError):
    code = "database_not_configured"

    def __init__(self) -> None:
        super().__init__("Persistence is not configured on this server (CODEWALK_DATABASE_URL is not set).")


_HTTP_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id_var.get(), details=details)
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=headers,
    )


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # pragma: no cover - registration guarantees type
        raise exc
    log = logger.warning if exc.status_code >= 500 else logger.info
    log("Application error %s: %s", exc.code, exc.message)
    return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers)


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        raise exc
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    # ``detail`` is set by framework code or our own routes and is client-safe;
    # fall back to the standard reason phrase when it is not a string.
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, code, message, headers=exc.headers)


def _validation_details(errors: list[Any]) -> list[ErrorDetail]:
    # Deliberately drop the "input" and "ctx" members: they echo request data,
    # which may contain source code or credentials.
    return [
        ErrorDetail(
            location=[part for part in err.get("loc", ()) if isinstance(part, str | int)],
            message=str(err.get("msg", "Invalid value")),
            type=str(err.get("type", "value_error")),
        )
        for err in errors
    ]


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        raise exc
    return error_response(
        422,
        "validation_error",
        "The request is invalid.",
        details=_validation_details(list(exc.errors())),
    )


async def _database_unavailable_handler(_: Request, exc: Exception) -> JSONResponse:
    # Driver messages include host names and sometimes user names: log the type only.
    logger.warning("Database unavailable: %s", type(exc).__name__)
    return error_response(503, "database_unavailable", "The database is currently unavailable.")


async def _integrity_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.info("Integrity error: %s", type(getattr(exc, "orig", exc)).__name__)
    return error_response(409, "conflict", "The request conflicts with existing data.")


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return error_response(500, "internal_error", "An unexpected error occurred.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    for database_error in (OperationalError, InterfaceError, PoolTimeoutError):
        app.add_exception_handler(database_error, _database_unavailable_handler)
    app.add_exception_handler(IntegrityError, _integrity_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
