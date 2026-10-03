"""Accounts and login sessions.

- Passwords are hashed with Argon2id (argon2-cffi defaults); hashes are upgraded
  transparently on login when the parameters change.
- A login creates a random 256-bit token that is sent to the browser in an
  httpOnly cookie. Only its SHA-256 is stored, so the sessions table cannot be
  used to impersonate anyone.
- Unknown emails and wrong passwords produce the same error, and an unknown
  email still costs one hash verification, so responses do not reveal which
  accounts exist. A disabled account is only reported after its correct
  password was given.
- Registration must report a taken email (there is no email verification step
  that could hide it); that endpoint is rate limited like login.
"""

from __future__ import annotations

import contextlib
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError
from app.db.models import User
from app.repositories.users import AuthSessionRepository, UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest

_hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths take the same time.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("Incorrect email or password.")


class AccountDisabledError(AppError):
    status_code = 403
    code = "account_disabled"

    def __init__(self) -> None:
        super().__init__("This account is disabled.")


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"

    def __init__(self) -> None:
        super().__init__("Sign in to continue.")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


class AuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.sessions = AuthSessionRepository(session)

    def register(self, data: RegisterRequest) -> tuple[User, str]:
        """Create an account and sign it in. Returns the user and the session token."""
        email = data.email
        if self.users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.", code="email_taken")
        try:
            user = self.users.create(
                email=email,
                name=data.name,
                password_hash=hash_password(data.password),
            )
            token = self._start_session(user)
            self.session.commit()
        except IntegrityError:  # concurrent registration with the same email
            self.session.rollback()
            raise ConflictError("An account with this email already exists.", code="email_taken") from None
        return user, token

    def login(self, data: LoginRequest) -> tuple[User, str]:
        user = self.users.get_by_email(data.email)
        if user is None:
            with contextlib.suppress(VerificationError):
                _hasher.verify(_DUMMY_HASH, data.password)
            raise InvalidCredentialsError()
        try:
            _hasher.verify(user.password_hash, data.password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise InvalidCredentialsError() from None
        if not user.is_active:
            raise AccountDisabledError()
        if _hasher.check_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
        now = datetime.now(UTC)
        user.last_login_at = now
        self.sessions.delete_expired(user.id, now)
        token = self._start_session(user)
        self.session.commit()
        return user, token

    def user_for_token(self, token: str) -> User | None:
        record = self.sessions.get_active(hash_token(token), datetime.now(UTC))
        if record is None or not record.user.is_active:
            return None
        return record.user

    def logout(self, token: str) -> None:
        self.sessions.delete_by_token(hash_token(token))
        self.session.commit()

    def _start_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions.create(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=self.settings.session_ttl_hours),
        )
        return token
