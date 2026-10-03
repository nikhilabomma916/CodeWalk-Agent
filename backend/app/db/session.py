"""Engine and session management.

The engine is created lazily and connects on first use, so the API starts (and
serves analysis) even when PostgreSQL is down; persistence endpoints then fail
with a clean 503 instead of a crash.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import anyio.to_thread
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.services.health import HealthCheckFailedError, HealthCheckNotConfiguredError

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str, *, pool_size: int = 5, connect_timeout: int = 5) -> None:
        self.engine: Engine = create_engine(
            url,
            pool_size=pool_size,
            max_overflow=pool_size,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": connect_timeout},
        )
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False, autoflush=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Database | None:
        if settings.database_url is None:
            return None
        return cls(
            settings.database_url.get_secret_value(),
            pool_size=settings.database_pool_size,
            connect_timeout=settings.database_connect_timeout_seconds,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> None:
        """Round-trip to the server; raises HealthCheckFailedError with a safe message."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            # The driver message can contain host names; it is logged, not returned.
            logger.warning("Database health check failed: %s", type(exc).__name__)
            raise HealthCheckFailedError("Database is not reachable") from exc

    def dispose(self) -> None:
        self.engine.dispose()


class DatabaseHealthCheck:
    name = "database"
    # The API still serves code analysis without a database, so an outage makes
    # the service "degraded" rather than unavailable.
    required = False

    def __init__(self, database: Database | None) -> None:
        self._database = database

    async def check(self) -> None:
        if self._database is None:
            raise HealthCheckNotConfiguredError("CODEWALK_DATABASE_URL is not set")
        await anyio.to_thread.run_sync(self._database.ping)
