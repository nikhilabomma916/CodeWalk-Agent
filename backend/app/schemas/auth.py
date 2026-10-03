from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.common import DisplayName

MIN_PASSWORD_LENGTH = 8
# Bounded so a huge password cannot be used to make hashing expensive.
MAX_PASSWORD_LENGTH = 128


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _validate_password(value: str) -> str:
    """Length plus a light mix rule: at least one letter and one digit or symbol."""
    if not value.strip():
        raise ValueError("must not be only whitespace")
    if not any(c.isalpha() for c in value):
        raise ValueError("must contain at least one letter")
    if all(c.isalpha() for c in value):
        raise ValueError("must contain at least one number or symbol")
    if len(set(value)) < 4:
        raise ValueError("is too repetitive")
    return value


Email = Annotated[EmailStr, Field(max_length=320), AfterValidator(_normalize_email)]
Password = Annotated[
    str,
    Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH),
    AfterValidator(_validate_password),
]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DisplayName
    email: Email
    password: Password

    @model_validator(mode="after")
    def _password_differs_from_email(self) -> RegisterRequest:
        lowered = self.password.lower()
        if lowered == self.email or lowered == self.email.split("@", 1)[0]:
            raise ValueError("password must not be your email address")
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    # Not validated against the policy: an old password may predate it.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    """The signed-in user's own account. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    created_at: datetime
    last_login_at: datetime | None
