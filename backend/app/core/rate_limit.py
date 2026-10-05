"""Sliding-window limits for login attempts and per-user request limits.

``AttemptLimiter`` keeps its state in this process only (with several API processes each keeps its
own counts). ``DatabaseAttemptLimiter`` shares the same limit across every process through
PostgreSQL; ``make_limiter`` picks it whenever a database is configured.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from collections import deque
from datetime import timedelta
from typing import Protocol

from sqlalchemy import Column, DateTime, Engine, MetaData, String, Table, delete, func, insert, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.metrics import METRICS

logger = logging.getLogger(__name__)

# Rows older than this belong to no window any more (the longest configurable window is one day).
_STALE_AFTER = timedelta(days=2)
# The table as the limiter uses it (the ORM model is app.db.models.RateLimitEvent).
RATE_LIMIT_EVENTS = Table(
    "rate_limit_events",
    MetaData(),
    Column("key_hash", String(64), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)


class RateLimiter(Protocol):
    """What callers use: both limiters below implement it.

    ``retry_after`` only inspects: it records nothing and counts no metric. ``acquire`` counts a
    refusal in ``codewalk_rate_limited_total``; a caller that refuses a request on the strength of
    ``retry_after`` counts it itself with ``METRICS.count_rate_limited(limiter.name)``.
    """

    name: str  # metrics label: a fixed limit name, never a key

    def retry_after(self, key: str) -> int | None: ...

    def acquire(self, key: str) -> int | None: ...

    def reset(self, key: str) -> None: ...


class AttemptLimiter:
    def __init__(
        self, max_attempts: int, window_seconds: float, *, max_keys: int = 100_000, name: str = "limit"
    ) -> None:
        self.name = name  # metrics label: a fixed limit name, never a key
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts.get(key)
        if attempts is None:
            return deque()
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        if not attempts:
            del self._attempts[key]
        return attempts

    def retry_after(self, key: str) -> int | None:
        """Seconds until another attempt is allowed, or None when not limited (inspection only)."""
        now = time.monotonic()
        with self._lock:
            attempts = self._recent(key, now)
            if len(attempts) < self.max_attempts:
                return None
            return max(1, int(attempts[0] + self.window_seconds - now) + 1)

    def acquire(self, key: str) -> int | None:
        """Check and record one attempt atomically: None when it is allowed (and now counted),
        otherwise the seconds until another attempt is allowed (nothing is recorded).

        Use this instead of ``retry_after`` followed by ``record_failure`` wherever every attempt
        counts: with the two separate calls, simultaneous requests can all pass the check before
        any of them is recorded, exceeding the limit.
        """
        now = time.monotonic()
        with self._lock:
            attempts = self._recent(key, now)
            if len(attempts) < self.max_attempts:
                self._append(key, now)
                return None
            retry = max(1, int(attempts[0] + self.window_seconds - now) + 1)
        METRICS.count_rate_limited(self.name)
        return retry

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._append(key, now)

    def _append(self, key: str, now: float) -> None:
        if key not in self._attempts and len(self._attempts) >= self.max_keys:
            # Bound memory: drop the oldest key (dicts keep insertion order).
            self._attempts.pop(next(iter(self._attempts)))
        attempts = self._attempts.setdefault(key, deque())
        attempts.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


class DatabaseAttemptLimiter:
    """The same sliding-window limit, shared by every API process through PostgreSQL.

    On serverless or multi-instance hosting each process has its own memory, so the in-process
    counter above would multiply the limit by the number of instances (and reset on every cold
    start). This one stores one row per attempt in ``rate_limit_events`` and serializes the check
    and the insert per key with a transaction-scoped advisory lock, so concurrent requests on any
    instance cannot exceed the limit. Keys are stored only as SHA-256 hashes (they contain client
    addresses and email addresses).

    If the database cannot be reached, the in-process limiter is used instead, so a limit always
    applies.
    """

    def __init__(self, engine: Engine, max_attempts: int, window_seconds: float, *, namespace: str) -> None:
        self.engine = engine
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.namespace = namespace
        self.name = namespace
        self.fallback = AttemptLimiter(max_attempts, window_seconds, name=namespace)

    def _hash(self, key: str) -> str:
        return hashlib.sha256(f"{self.namespace}:{key}".encode("utf-8", "surrogatepass")).hexdigest()

    def retry_after(self, key: str) -> int | None:
        """Seconds until another attempt is allowed, or None (nothing is recorded)."""
        key_hash = self._hash(key)
        window = timedelta(seconds=self.window_seconds)
        try:
            with self.engine.connect() as connection:
                now = connection.execute(select(func.now())).scalar_one()
                count, oldest = connection.execute(
                    select(func.count(), func.min(RATE_LIMIT_EVENTS.c.occurred_at)).where(
                        RATE_LIMIT_EVENTS.c.key_hash == key_hash,
                        RATE_LIMIT_EVENTS.c.occurred_at > now - window,
                    )
                ).one()
        except SQLAlchemyError:
            return self.fallback.retry_after(key)
        if count < self.max_attempts:
            return None
        return max(1, int((oldest + window - now).total_seconds()) + 1)

    def acquire(self, key: str) -> int | None:
        """Check and record one attempt atomically (see ``AttemptLimiter.acquire``)."""
        key_hash = self._hash(key)
        window = timedelta(seconds=self.window_seconds)
        try:
            with self.engine.begin() as connection:
                connection.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key_hash, 0))))
                now = connection.execute(select(func.now())).scalar_one()
                connection.execute(
                    delete(RATE_LIMIT_EVENTS).where(
                        RATE_LIMIT_EVENTS.c.key_hash == key_hash,
                        RATE_LIMIT_EVENTS.c.occurred_at <= now - window,
                    )
                )
                count, oldest = connection.execute(
                    select(func.count(), func.min(RATE_LIMIT_EVENTS.c.occurred_at)).where(
                        RATE_LIMIT_EVENTS.c.key_hash == key_hash
                    )
                ).one()
                if count >= self.max_attempts:
                    METRICS.count_rate_limited(self.namespace)
                    return max(1, int((oldest + window - now).total_seconds()) + 1)
                connection.execute(insert(RATE_LIMIT_EVENTS).values(key_hash=key_hash, occurred_at=now))
                if secrets.randbelow(200) == 0:  # occasionally drop every key's stale rows
                    connection.execute(
                        delete(RATE_LIMIT_EVENTS).where(RATE_LIMIT_EVENTS.c.occurred_at < now - _STALE_AFTER)
                    )
                return None
        except SQLAlchemyError:
            logger.warning("Shared rate limit unavailable (%s); using this process's limit", self.namespace)
            return self.fallback.acquire(key)

    def reset(self, key: str) -> None:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    delete(RATE_LIMIT_EVENTS).where(RATE_LIMIT_EVENTS.c.key_hash == self._hash(key))
                )
        except SQLAlchemyError:
            logger.warning("Shared rate limit unavailable (%s); reset only in this process", self.namespace)
        self.fallback.reset(key)


def make_limiter(
    engine: Engine | None, max_attempts: int, window_seconds: float, *, namespace: str
) -> RateLimiter:
    """Shared through PostgreSQL when a database is configured, else in-process."""
    if engine is None:
        return AttemptLimiter(max_attempts, window_seconds, name=namespace)
    return DatabaseAttemptLimiter(engine, max_attempts, window_seconds, namespace=namespace)
