"""Module 23: metrics for errors, rate limits and AI usage; log redaction; readiness checks; no AI retries."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.core.logging import RedactingFormatter, configure_logging, redact
from app.core.metrics import METRICS, Metrics, timed
from app.core.rate_limit import AttemptLimiter, DatabaseAttemptLimiter, RateLimiter
from app.services.ai.base import AIRateLimitedError, AITimeoutError, AIUnavailableError
from app.services.ai.outputs import ModelExplanation
from app.services.ai.providers.anthropic import AnthropicProvider
from app.services.ai.providers.openai_compatible import OPENROUTER, OpenAICompatibleProvider
from app.services.ai.service import AIService
from tests.ai_stub import StubProvider
from tests.conftest import build_app, make_settings

EXPLANATION = {
    "explanation": "Adds numbers.",
    "cause": "-",
    "impact": "-",
    "suggested_fix": "-",
    "related_locations": [],
    "confidence": "high",
    "warnings": [],
}


# --- metrics ----------------------------------------------------------------------------------------


def test_error_responses_are_counted_by_status_and_code(
    client_factory: Callable[[FastAPI], TestClient],
) -> None:
    client = client_factory(build_app())
    before = METRICS.counter_value("errors", ("404", "not_found"))
    client.get("/api/v1/no-such-route")
    client.get("/api/v1/no-such-route")
    assert METRICS.counter_value("errors", ("404", "not_found")) == before + 2
    assert 'codewalk_error_responses_total{status="404",code="not_found"}' in METRICS.render()


def test_rate_limit_refusals_are_counted_by_limit_name() -> None:
    limiter = AttemptLimiter(1, 60, name="unit-test-limit")
    before = METRICS.counter_value("rate_limited", ("unit-test-limit",))
    assert limiter.acquire("k") is None
    assert limiter.acquire("k") is not None
    assert METRICS.counter_value("rate_limited", ("unit-test-limit",)) == before + 1


@pytest.mark.parametrize(
    "limiter",
    [
        AttemptLimiter(1, 60, name="inspect-only"),
        # SQLite has no table here: the shared limiter inspects through its in-process fallback.
        DatabaseAttemptLimiter(create_engine("sqlite://"), 1, 60, namespace="inspect-only"),
    ],
)
def test_retry_after_inspection_counts_no_rejection(limiter: RateLimiter) -> None:
    before = METRICS.counter_value("rate_limited", ("inspect-only",))
    assert limiter.retry_after("k") is None  # not limited: nothing to count
    assert limiter.acquire("k") is None
    for _ in range(3):
        assert limiter.retry_after("k") is not None  # limited, but only looked at
    assert METRICS.counter_value("rate_limited", ("inspect-only",)) == before
    assert limiter.acquire("k") is not None  # an actual refusal
    assert METRICS.counter_value("rate_limited", ("inspect-only",)) == before + 1


def test_ai_requests_record_provider_model_outcome_tokens_and_cost() -> None:
    metrics = Metrics()
    metrics.observe_ai(
        "openrouter",
        "vendor/model",
        "ok",
        1.5,
        {"input_tokens": 100, "output_tokens": 20, "cost_microusd": 1234},
    )
    metrics.observe_ai("openrouter", "vendor/model", "ai_timeout", 90.0)
    text = metrics.render()
    count = "codewalk_ai_request_duration_seconds_count"
    assert f'{count}{{provider="openrouter",model="vendor/model",outcome="ok"}} 1' in text
    assert 'outcome="ai_timeout"} 1' in text
    assert (
        'codewalk_ai_tokens_total{provider="openrouter",model="vendor/model",direction="input"} 100' in text
    )
    assert (
        'codewalk_ai_tokens_total{provider="openrouter",model="vendor/model",direction="output"} 20' in text
    )
    assert 'codewalk_ai_cost_microusd_total{provider="openrouter",model="vendor/model"} 1234' in text


def test_ai_service_records_success_and_normalized_failures(caplog: pytest.LogCaptureFixture) -> None:
    secret_prompt = "def leaked(): return 'PROMPT-TEXT-MUST-NOT-BE-LOGGED'"
    stub = StubProvider(
        name="stubai",
        model="stub-model-x",
        answers=[EXPLANATION, AITimeoutError(), AIRateLimitedError("slow")],
    )
    service = AIService(make_settings(ai_enabled=True), provider=stub)
    with caplog.at_level(logging.INFO):
        service.run(stub, "system", secret_prompt, ModelExplanation)
        for _ in range(2):
            with pytest.raises((AITimeoutError, AIRateLimitedError)):
                service.run(stub, "system", secret_prompt, ModelExplanation)
    text = METRICS.render()
    for outcome in ("ok", "ai_timeout", "ai_rate_limited"):
        assert (
            f'codewalk_ai_request_duration_seconds_count{{provider="stubai",model="stub-model-x",outcome="{outcome}"}}'
            in text
        )
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("AI request")]
    assert [line.split("outcome=")[1].split()[0] for line in lines] == ["ok", "ai_timeout", "ai_rate_limited"]
    assert "PROMPT-TEXT" not in caplog.text


def _fail_with_specific_outcome() -> None:
    with timed("unit_operation") as metric:
        metric["outcome"] = "specific_code"
        raise ValueError("boom")


def test_timed_keeps_a_specific_outcome() -> None:
    with pytest.raises(ValueError, match="boom"):
        _fail_with_specific_outcome()
    assert 'operation="unit_operation",outcome="specific_code"' in METRICS.render()


# --- log redaction ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "Bearer abcdefghijklmnop1234",
        "sk-proj-" + "a" * 40,
        "sk-ant-api03-" + "b" * 40,
        "sk-or-v1-" + "c" * 40,
        "ghp_" + "d" * 36,
        "gho_" + "e" * 36,
        "AIza" + "f" * 35,
        "pa-" + "g" * 40,
        "postgresql+psycopg://codewalk:hunter2-database-password@db.example.com/codewalk",
        'api_key="raw-api-key-value"',
        "client_secret=raw-client-secret-value",
        "v1.0123456789abcdef.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    ],
)
def test_credentials_are_redacted_from_logs(secret: str) -> None:
    redacted = redact(f"something failed: {secret} (retrying)")
    for fragment in (
        "abcdefghijklmnop1234",
        "a" * 40,
        "b" * 40,
        "c" * 40,
        "d" * 36,
        "e" * 36,
        "f" * 35,
        "g" * 40,
        "hunter2-database-password",
        "raw-api-key-value",
        "raw-client-secret-value",
        "A" * 30,
    ):
        assert fragment not in redacted
    assert "something failed" in redacted


def test_ordinary_log_lines_are_unchanged() -> None:
    line = (
        "AI request provider=openai model=gpt-5 outcome=ok duration_ms=812 input_tokens=120 output_tokens=40"
    )
    assert redact(line) == line
    assert redact("GET /api/v1/projects 200 in 12 ms") == "GET /api/v1/projects 200 in 12 ms"


def test_the_console_handler_redacts_messages_and_tracebacks() -> None:
    configure_logging(make_settings(log_format="json"))
    handler = next(h for h in logging.getLogger().handlers if h.get_name() == "codewalk-console")
    assert isinstance(handler.formatter, RedactingFormatter)
    stream = io.StringIO()
    previous = handler.setStream(stream)  # type: ignore[attr-defined]
    try:
        try:
            raise RuntimeError("connect failed for postgresql://u:hunter2-secret@db/x")
        except RuntimeError:
            logging.getLogger("unit").exception("token ghp_%s was rejected", "x" * 36)
    finally:
        handler.setStream(previous)  # type: ignore[attr-defined]
    output = stream.getvalue()
    assert "hunter2-secret" not in output
    assert "x" * 36 not in output
    assert json.loads(output.strip().splitlines()[-1])["level"] == "ERROR"


# --- readiness checks ------------------------------------------------------------------------------


def health(client: TestClient) -> dict[str, str]:
    return {check["name"]: check["status"] for check in client.get("/api/v1/health").json()["checks"]}


def test_providers_are_reported_without_being_called(client_factory: Callable[[FastAPI], TestClient]) -> None:
    off = health(client_factory(build_app()))
    assert off["ai_provider"] == "not_configured"
    assert off["embeddings"] == "not_configured"
    # Enabled but without a key: degraded (not unavailable), and still no network call.
    misconfigured = client_factory(build_app(ai_enabled=True, ai_provider="gemini", ai_model="m"))
    response = misconfigured.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert health(misconfigured)["ai_provider"] == "fail"


# --- no automatic AI retries -------------------------------------------------------------------------


def test_the_anthropic_provider_does_not_retry() -> None:
    assert AnthropicProvider(api_key="sk-ant-test").__dict__["_client"].max_retries == 0


def test_compatible_providers_make_exactly_one_call_on_failure() -> None:
    calls: list[int] = []

    def server_error(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={})

    provider = OpenAICompatibleProvider(
        api_key="k", model="m", transport=httpx.MockTransport(server_error), profile=OPENROUTER
    )
    service = AIService(make_settings(ai_enabled=True), provider=provider)
    with pytest.raises(AIUnavailableError, match="temporarily unavailable"):
        service.run(provider, "s", "u", ModelExplanation)
    assert calls == [1]
