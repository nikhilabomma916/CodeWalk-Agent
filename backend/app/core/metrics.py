"""Process-local, bounded operational metrics in the Prometheus text format.

Recorded: HTTP requests (by method, route template, and status class), database statements, and
the latency of CodeWalk's main operations (code analysis, search, project index builds, semantic
indexing, AI provider calls, agent runs). Every label comes from a fixed set (route templates of
the application, operation names in this code, outcome codes), never from user input, ids, or
paths, so the number of series is bounded and no user data is exposed.

Values live in this process only: with several API workers each exposes its own counts, and a
scraper sums them. ``GET /metrics`` (outside ``/api``; not routed by the reverse proxy) returns them
when ``CODEWALK_METRICS_ENABLED`` is true.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

# Seconds. Covers a fast metadata query up to a long agent run.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
# Hard cap on series per metric: a bug that produced unbounded labels cannot exhaust memory.
MAX_SERIES = 500
OVERFLOW = ("_other",)


@dataclass
class Histogram:
    counts: list[int] = field(default_factory=lambda: [0] * len(BUCKETS))
    total: float = 0.0
    count: int = 0

    def observe(self, seconds: float) -> None:
        self.count += 1
        self.total += seconds
        for i, bound in enumerate(BUCKETS):
            if seconds <= bound:
                self.counts[i] += 1
                break


class _Family:
    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...]) -> None:
        self.name = name
        self.help = help_text
        self.label_names = label_names
        self.series: dict[tuple[str, ...], Histogram] = {}

    def observe(self, labels: tuple[str, ...], seconds: float) -> None:
        series = self.series.get(labels)
        if series is None:
            if len(self.series) >= MAX_SERIES:
                labels = OVERFLOW * len(self.label_names)
            series = self.series.setdefault(labels, Histogram())
        series.observe(seconds)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(pairs: list[str]) -> str:
    return "{" + ",".join(pairs) + "}" if pairs else ""


def _le(bound: str) -> str:
    return 'le="' + bound + '"'


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self._families = {
            "requests": _Family(
                "codewalk_http_request_duration_seconds",
                "HTTP requests by method, route template, and status class.",
                ("method", "route", "status"),
            ),
            "operations": _Family(
                "codewalk_operation_duration_seconds",
                "CodeWalk operations by name and outcome.",
                ("operation", "outcome"),
            ),
            "database": _Family(
                "codewalk_db_statement_duration_seconds",
                "Database statements executed by the application.",
                (),
            ),
        }

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self._families["requests"].observe((method, route, f"{status // 100}xx"), seconds)

    def observe(self, operation: str, seconds: float, outcome: str = "ok") -> None:
        with self._lock:
            self._families["operations"].observe((operation, outcome), seconds)

    def observe_statement(self, seconds: float) -> None:
        with self._lock:
            self._families["database"].observe((), seconds)

    def render(self) -> str:
        lines = [
            "# HELP codewalk_process_start_time_seconds Start time of this API process (Unix time).",
            "# TYPE codewalk_process_start_time_seconds gauge",
            f"codewalk_process_start_time_seconds {self.started:.3f}",
        ]
        with self._lock:
            for family in self._families.values():
                lines.append(f"# HELP {family.name} {family.help}")
                lines.append(f"# TYPE {family.name} histogram")
                for labels, series in sorted(family.series.items()):
                    pairs = [f'{n}="{_escape(v)}"' for n, v in zip(family.label_names, labels, strict=True)]
                    cumulative = 0
                    for bound, count in zip(BUCKETS, series.counts, strict=True):
                        cumulative += count
                        lines.append(f"{family.name}_bucket{_labels([*pairs, _le(str(bound))])} {cumulative}")
                    lines.append(f"{family.name}_bucket{_labels([*pairs, _le('+Inf')])} {series.count}")
                    lines.append(f"{family.name}_sum{_labels(pairs)} {series.total:.6f}")
                    lines.append(f"{family.name}_count{_labels(pairs)} {series.count}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()


@contextmanager
def timed(operation: str) -> Iterator[dict[str, str]]:
    """Time a block as ``operation``. The block may set ``outcome`` in the yielded dict; an exception
    is recorded as ``error`` (and re-raised)."""
    result = {"outcome": "ok"}
    started = time.perf_counter()
    try:
        yield result
    except BaseException:
        result["outcome"] = "error"
        raise
    finally:
        METRICS.observe(operation, time.perf_counter() - started, result["outcome"])
