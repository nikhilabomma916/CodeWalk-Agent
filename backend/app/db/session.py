"""Engine and session management.

The engine is created lazily and connects on first use, so the API starts (and
serves analysis) even when PostgreSQL is down; persistence endpoints then fail
with a clean 503 instead of a crash.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import anyio.to_thread
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.metrics import METRICS
from app.services.health import HealthCheckFailedError, HealthCheckNotConfiguredError

logger = logging.getLogger(__name__)


class Database:
    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 5,
        connect_timeout: int = 5,
        statement_timeout_seconds: float | None = None,
    ) -> None:
        connect_args: dict[str, Any] = {"connect_timeout": connect_timeout}
        if statement_timeout_seconds is not None:
            connect_args["options"] = f"-c statement_timeout={round(statement_timeout_seconds * 1000)}"
        self.engine: Engine = create_engine(
            url,
            pool_size=pool_size,
            max_overflow=pool_size,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args=connect_args,
        )
        _time_statements(self.engine)
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False, autoflush=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Database | None:
        if settings.database_url is None:
            return None
        return cls(
            settings.database_url.get_secret_value(),
            pool_size=settings.database_pool_size,
            connect_timeout=settings.database_connect_timeout_seconds,
            statement_timeout_seconds=settings.database_statement_timeout_seconds,
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


def _time_statements(engine: Engine) -> None:
    """Record every statement's duration in the metrics (no SQL text or parameters)."""

    @event.listens_for(engine, "before_cursor_execute")
    def _started(conn: Any, *_: Any) -> None:
        conn.info["codewalk_statement_started"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _finished(conn: Any, *_: Any) -> None:
        started = conn.info.pop("codewalk_statement_started", None)
        if started is not None:
            METRICS.observe_statement(time.perf_counter() - started)


class DatabaseHealthCheck:
    name = "database"

    def __init__(self, database: Database | None, *, required: bool = False) -> None:
        self._database = database
        # Outside production the API still serves code analysis without a database, so an outage
        # makes the service "degraded". In production sign-in and projects need it: an outage
        # makes the service not ready (503), so health checks and the proxy stop routing to it.
        self.required = required

    async def check(self) -> None:
        if self._database is None:
            raise HealthCheckNotConfiguredError("CODEWALK_DATABASE_URL is not set")
        await anyio.to_thread.run_sync(self._database.ping)
