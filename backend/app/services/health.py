"""Health reporting.

Liveness means the process can answer requests. Readiness additionally runs
every registered ``HealthCheck``. Dependencies (database, AI provider, ...)
register a check when their module integrates them; until then they are
simply absent from the report rather than being reported as healthy.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from app.schemas.health import CheckStatus, DependencyCheckResult, HealthResponse, OverallStatus

logger = logging.getLogger(__name__)


class HealthCheckFailedError(Exception):
    """Raised by a check to report a client-safe failure reason."""


class HealthCheckNotConfiguredError(Exception):
    """Raised by a check whose dependency is intentionally not configured.

    Reported as ``not_configured``; it neither passes nor degrades the service.
    """


class HealthCheck(Protocol):
    name: str
    required: bool

    async def check(self) -> None:
        """Return normally when healthy; raise ``HealthCheckFailedError`` (or any error) otherwise."""
        ...


class HealthService:
    def __init__(
        self,
        *,
        service_name: str,
        version: str,
        environment: str,
        checks: Sequence[HealthCheck] = (),
        check_timeout_seconds: float = 3.0,
    ) -> None:
        self._service_name = service_name
        self._version = version
        self._environment = environment
        self._checks = list(checks)
        self._timeout = check_timeout_seconds
        self._started_monotonic = time.monotonic()

    def register(self, check: HealthCheck) -> None:
        self._checks.append(check)

    async def report(self) -> HealthResponse:
        results = await asyncio.gather(*(self._run(check) for check in self._checks))
        return HealthResponse(
            status=self._aggregate(results),
            service=self._service_name,
            version=self._version,
            environment=self._environment,
            timestamp=datetime.now(UTC),
            uptime_seconds=round(time.monotonic() - self._started_monotonic, 3),
            checks=list(results),
        )

    async def _run(self, check: HealthCheck) -> DependencyCheckResult:
        started = time.perf_counter()
        status = CheckStatus.PASS
        detail: str | None = None
        try:
            await asyncio.wait_for(check.check(), timeout=self._timeout)
        except TimeoutError:
            status, detail = CheckStatus.FAIL, f"Timed out after {self._timeout:g}s"
        except HealthCheckNotConfiguredError as exc:
            status, detail = CheckStatus.NOT_CONFIGURED, str(exc) or "Not configured"
        except HealthCheckFailedError as exc:
            status, detail = CheckStatus.FAIL, str(exc) or "Check failed"
        except Exception:
            # Internal error text may contain hosts or credentials; log it, don't return it.
            logger.exception("Health check %r raised an unexpected error", check.name)
            status, detail = CheckStatus.FAIL, "Check raised an unexpected error"
        if status is CheckStatus.FAIL:
            logger.warning("Health check %r failed: %s", check.name, detail)
        return DependencyCheckResult(
            name=check.name,
            status=status,
            required=check.required,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            detail=detail,
        )

    @staticmethod
    def _aggregate(results: Sequence[DependencyCheckResult]) -> OverallStatus:
        failed = [r for r in results if r.status is CheckStatus.FAIL]
        if any(r.required for r in failed):
            return OverallStatus.UNAVAILABLE
        if failed:
            return OverallStatus.DEGRADED
        return OverallStatus.OK
