"""Error response contract shared by every endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """A single field-level problem (used for validation errors)."""

    location: list[str | int] = Field(description="Path to the offending input, e.g. ['body', 'name'].")
    message: str
    type: str = Field(description="Machine-readable error type.")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code, e.g. 'validation_error'.")
    message: str = Field(description="Human-readable summary safe to show to users.")
    request_id: str | None = Field(
        default=None, description="Correlates the error with server logs (X-Request-ID)."
    )
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
