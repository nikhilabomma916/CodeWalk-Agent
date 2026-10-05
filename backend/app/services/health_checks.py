"""Readiness checks beyond the database (Module 23). None of them calls an external service.

- ``schema``: the database is migrated to the code's Alembic head. Required in production: code
  running against an older schema fails on the new tables, so the instance should not take traffic.
- ``ai_provider`` / ``embeddings``: configured, off (``not_configured``), or misconfigured (``fail``,
  which degrades the service without making it unavailable).
- ``typescript_worker``: Node and the analyzer are installed (``not_configured`` otherwise).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import anyio
from sqlalchemy import text

from app.core.config import BACKEND_DIR
from app.db.session import Database
from app.services.analysis.typescript_worker import TypeScriptWorker
from app.services.health import HealthCheckFailedError, HealthCheckNotConfiguredError


@lru_cache(maxsize=1)
def alembic_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_current_head()


class SchemaHealthCheck:
    name = "schema"

    def __init__(self, database: Database | None, *, required: bool = False) -> None:
        self._database = database
        self.required = required

    def _current(self, database: Database) -> str | None:
        with database.engine.connect() as connection:
            exists = connection.execute(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            ).scalar()
            if not exists:
                return None
            value = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return str(value) if value is not None else None

    async def check(self) -> None:
        database = self._database
        if database is None:
            raise HealthCheckNotConfiguredError("CODEWALK_DATABASE_URL is not set")
        try:
            current = await anyio.to_thread.run_sync(self._current, database)
        except Exception as exc:
            raise HealthCheckFailedError("Schema version unavailable") from exc
        head = alembic_head()
        if current != head:
            raise HealthCheckFailedError(
                f"Database schema at {current or 'no revision'}; the code needs {head}"
            )


class ConfigurationHealthCheck:
    """A provider that is either off, configured, or misconfigured; never contacted by the check."""

    required = False

    def __init__(self, name: str, state: Callable[[], tuple[bool, bool, str | None]]) -> None:
        self.name = name
        self._state = state  # (enabled, configured, detail)

    async def check(self) -> None:
        enabled, configured, detail = self._state()
        if not enabled:
            raise HealthCheckNotConfiguredError("Off")
        if not configured:
            raise HealthCheckFailedError(detail or "Enabled but not configured")


class TypeScriptWorkerHealthCheck:
    name = "typescript_worker"
    required = False

    def __init__(self, worker: TypeScriptWorker) -> None:
        self._worker = worker

    async def check(self) -> None:
        reason = self._worker.unavailable_reason()
        if reason:
            raise HealthCheckNotConfiguredError(reason)
