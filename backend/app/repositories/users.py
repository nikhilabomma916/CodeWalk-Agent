"""Data access for users and their login sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import AuthSession, User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, email: str, name: str, password_hash: str) -> User:
        user = User(email=email, name=name, password_hash=password_hash)
        self.session.add(user)
        self.session.flush()
        return user

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))


class AuthSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> AuthSession:
        record = AuthSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(record)
        self.session.flush()
        return record

    def get_active(self, token_hash: str, now: datetime) -> AuthSession | None:
        return self.session.scalar(
            select(AuthSession)
            .options(joinedload(AuthSession.user))
            .where(AuthSession.token_hash == token_hash, AuthSession.expires_at > now)
        )

    def delete_by_token(self, token_hash: str) -> None:
        self.session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
        self.session.flush()

    def delete_expired(self, user_id: uuid.UUID, now: datetime) -> None:
        self.session.execute(
            delete(AuthSession).where(AuthSession.user_id == user_id, AuthSession.expires_at <= now)
        )
        self.session.flush()
