"""Registration, login, logout, and the current user.

The session token travels only in an httpOnly cookie (never in a response
body), so page scripts cannot read it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuthServiceDep, CurrentUserDep, LoginLimiterDep, RegisterLimiterDep, SettingsDep
from app.core.config import Settings
from app.core.exceptions import AppError
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.schemas.errors import ErrorResponse
from app.services.auth import InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])


class TooManyAttemptsError(AppError):
    status_code = 429
    code = "too_many_attempts"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many attempts. Try again in {retry_after} seconds.")
        self.headers = {"Retry-After": str(retry_after)}


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
    responses={
        409: {"model": ErrorResponse, "description": "An account with this email exists (`email_taken`)."},
        429: {"model": ErrorResponse, "description": "Too many registrations from this address."},
    },
)
def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    limiter: RegisterLimiterDep,
) -> UserResponse:
    key = f"register:{_client(request)}"
    if (retry_after := limiter.retry_after(key)) is not None:
        raise TooManyAttemptsError(retry_after)
    limiter.record_failure(key)  # every attempt counts toward the limit
    user, token = auth.register(data)
    _set_session_cookie(response, settings, token)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=UserResponse,
    summary="Sign in",
    responses={
        401: {"model": ErrorResponse, "description": "Incorrect email or password (`invalid_credentials`)."},
        403: {"model": ErrorResponse, "description": "The account is disabled (`account_disabled`)."},
        429: {"model": ErrorResponse, "description": "Too many failed attempts (`too_many_attempts`)."},
    },
)
def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    limiter: LoginLimiterDep,
) -> UserResponse:
    key = f"login:{_client(request)}:{data.email}"
    if (retry_after := limiter.retry_after(key)) is not None:
        raise TooManyAttemptsError(retry_after)
    try:
        user, token = auth.login(data)
    except InvalidCredentialsError:
        limiter.record_failure(key)
        raise
    limiter.reset(key)
    _set_session_cookie(response, settings, token)
    return UserResponse.model_validate(user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description="Ends the current session and clears the cookie. Succeeds even when not signed in.",
)
def logout(request: Request, auth: AuthServiceDep, settings: SettingsDep) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        auth.logout(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.session_cookie_name, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The signed-in user",
    responses={401: {"model": ErrorResponse, "description": "Not signed in (`not_authenticated`)."}},
)
def me(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)
