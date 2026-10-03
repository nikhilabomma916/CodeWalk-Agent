"""AI endpoints (Modules 7 and 8) against real PostgreSQL, with a controlled provider.

The stub provider stands in for the model, so these tests check CodeWalk's own
logic: availability states, authorization, validation, project context,
normalization of answers, persistence, and that nothing modifies files.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.ai.base import AIRateLimitedError, AITimeoutError, AIUnavailableError
from app.services.ai.service import AIService
from tests.ai_stub import StubProvider, analysis, explanation, finding, fix
from tests.conftest import build_app, make_settings
from tests.db.conftest import register

CART = (
    "from shop.pricing import price_of\n"
    "\n"
    "def cart_total(items):\n"
    "    for item in items:\n"
    "        total += price_of(item)\n"
    "    return total\n"
)
PRICING = "def price_of(item):\n    return item.price\n"
CHECKOUT = "from shop.cart import cart_total\n\nprint(cart_total([]))\n"

UNDEFINED_TOTAL = {
    "id": "d1",
    "severity": "error",
    "message": "Undefined name `total`",
    "source": "ruff",
    "code": "F821",
    "category": "lint",
    "line": 5,
    "column": 9,
    "end_line": 5,
    "end_column": 14,
}


@pytest.fixture
def stub(db_app: FastAPI, database_url: str) -> StubProvider:
    provider = StubProvider()
    db_app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url), provider=provider
    )
    return provider


@pytest.fixture
def shop(api: TestClient) -> dict[str, Any]:
    project = api.post("/api/v1/projects", json={"name": "Shop"}).json()
    files = {}
    for path, content in (
        ("shop/cart.py", CART),
        ("shop/pricing.py", PRICING),
        ("shop/checkout.py", CHECKOUT),
    ):
        files[path] = api.post(
            f"/api/v1/projects/{project['id']}/files", json={"path": path, "content": content}
        ).json()["file"]
    return {"id": project["id"], "files": files}


def body(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "code": CART,
        "language": "python",
        "file_path": "shop/cart.py",
        "diagnostics": [UNDEFINED_TOTAL],
    }
    values.update(overrides)
    return values


# --- availability and access -------------------------------------------------------------


def test_status_is_safe_and_makes_no_provider_call(
    database_url: str, client_factory: Callable[[FastAPI], TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    emails = iter(f"status{i}@example.com" for i in range(3))

    def signed_in(app: FastAPI) -> TestClient:
        client = client_factory(app)
        register(client, email=next(emails))
        return client

    disabled = signed_in(build_app(database_url=database_url)).get("/api/v1/ai/status").json()
    assert disabled["enabled"] is False
    assert disabled["available"] is False
    assert "CODEWALK_AI_ENABLED" in disabled["detail"]

    missing = signed_in(build_app(database_url=database_url, ai_enabled=True)).get("/api/v1/ai/status").json()
    assert missing["enabled"] is True
    assert missing["configured"] is False
    assert "ANTHROPIC_API_KEY" in missing["detail"]

    secret = "sk-ant-api03-this-must-never-leak"
    client = signed_in(build_app(database_url=database_url, ai_enabled=True, ai_api_key=secret))
    response = client.get("/api/v1/ai/status")
    status = response.json()
    assert status["available"] is True
    assert (status["provider"], status["model"]) == ("anthropic", "claude-opus-5-5")
    assert secret not in response.text
    assert "general_review" in status["analysis_types"]


def test_ai_requires_sign_in(anonymous: TestClient) -> None:
    assert anonymous.get("/api/v1/ai/status").status_code == 401
    for path in ("analyze", "explain", "fix-suggestion"):
        response = anonymous.post(f"/api/v1/ai/{path}", json=body(diagnostic=UNDEFINED_TOTAL))
        assert response.status_code == 401, path


def test_disabled_ai_is_reported_and_deterministic_analysis_still_works(api: TestClient) -> None:
    response = api.post("/api/v1/ai/analyze", json=body())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_disabled"
    explain = api.post("/api/v1/ai/explain", json=body(diagnostic=UNDEFINED_TOTAL))
    assert explain.json()["error"]["code"] == "ai_disabled"
    deterministic = api.post("/api/v1/analysis/code", json={"code": CART, "language": "python"})
    assert deterministic.status_code == 200
    assert any("total" in d["message"] for d in deterministic.json()["diagnostics"])


def test_missing_credential_is_reported(
    database_url: str, signed_in: Callable[[FastAPI], TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = signed_in(build_app(database_url=database_url, ai_enabled=True))
    response = client.post("/api/v1/ai/analyze", json=body())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


# --- Module 7: analysis ------------------------------------------------------------------


def test_analysis_normalizes_findings_and_records_them(
    api: TestClient, stub: StubProvider, shop: dict[str, Any]
) -> None:
    stub.answers.append(
        analysis(
            finding(line=5, related_diagnostic_id="d1", title="Accumulator never initialised"),
            finding(line=99, title="Points outside the file"),
            finding(line=3, related_diagnostic_id="invented", category="maintainability", basis="inferred"),
        )
    )
    response = api.post("/api/v1/ai/analyze", json=body(project_id=shop["id"], analysis_type="bug_detection"))
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["provider"] == "stub"
    assert result["analysis_type"] == "bug_detection"
    assert result["confidence"] == "medium"
    titles = [f["title"] for f in result["findings"]]
    assert titles == ["Accumulator never initialised", "Iterates over the wrong name"]
    first, second = result["findings"]
    assert (first["line"], first["column"], first["end_line"], first["end_column"]) == (5, 9, 5, 32)
    assert first["related_diagnostic_id"] == "d1"
    assert second["related_diagnostic_id"] is None  # unknown ids are not passed through
    assert second["basis"] == "inferred"
    assert any("discarded" in w for w in result["warnings"])

    # Project context: the imported definition and the importer, never other projects' data.
    assert result["context"]["used"] is True
    assert "shop/pricing.py" in result["context"]["files"]
    prompt = stub.requests[0]
    assert '<context file="shop/pricing.py"' in prompt.user
    assert "5 |         total += price_of(item)" in prompt.user  # numbered lines
    assert "id=d1 error [ruff F821]" in prompt.user
    assert "Do not repeat them as findings" in prompt.system
    assert set(prompt.schema["properties"]) == {"summary", "findings", "confidence", "warnings"}

    # Recorded: analysis metadata and findings, not the source code.
    record = api.get(f"/api/v1/analyses/{result['record_id']}").json()
    assert record["analysis_type"] == "ai_review"
    assert record["details"]["model"] == "stub-model"
    assert CART not in json.dumps(record["details"])
    events = api.get("/api/v1/history?event_type=ai.analyzed").json()["items"]
    assert len(events) == 1
    assert events[0]["file_path"] == "shop/cart.py"
    assert events[0]["details"]["diagnostic_count"] == 2


def test_analysis_without_project_is_not_recorded(api: TestClient, stub: StubProvider) -> None:
    stub.answers.append(analysis())
    result = api.post("/api/v1/ai/analyze", json=body()).json()
    assert result["findings"] == []
    assert result["record_id"] is None
    assert result["context"]["used"] is False
    assert "<context" not in stub.requests[0].user
    assert api.get("/api/v1/history").json()["total"] == 0


def test_large_files_are_windowed(api: TestClient, stub: StubProvider) -> None:
    code = "".join(f"value_{i} = {i}\n" for i in range(9000))
    stub.answers.append(analysis(finding(line=3, title="far away"), finding(line=5000, title="nearby")))
    request = body(
        code=code, file_path="big.py", diagnostics=[], selected_range={"start_line": 5000, "end_line": 5001}
    )
    result = api.post("/api/v1/ai/analyze", json=request).json()
    assert [f["title"] for f in result["findings"]] == ["nearby"]
    assert any("only lines 4850-5150" in w for w in result["warnings"])
    assert "value_3 = 3" not in stub.requests[0].user


# --- Module 8: explanations --------------------------------------------------------------


def test_explanation_keeps_only_real_locations(
    api: TestClient, stub: StubProvider, shop: dict[str, Any]
) -> None:
    stub.answers.append(
        explanation(
            related_locations=[
                {"file_path": "shop/pricing.py", "line": 1, "reason": "price_of is defined here"},
                {"file_path": "shop/cart.py", "line": 500, "reason": "line outside the file"},
                {"file_path": "../../etc/passwd", "line": 1, "reason": "invented"},
                {"file_path": "shop/invented.py", "line": 3, "reason": "invented"},
            ]
        )
    )
    response = api.post("/api/v1/ai/explain", json=body(project_id=shop["id"], diagnostic=UNDEFINED_TOTAL))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["diagnostic_id"] == "d1"
    assert result["problem"] == "Undefined name `total`"
    assert result["cause"] == "The accumulator is never initialised."
    assert result["impact"].startswith("The function raises")
    assert result["suggested_fix"].startswith("Initialise")
    assert result["related_code_locations"] == [
        {"file_path": "shop/pricing.py", "line": 1, "reason": "price_of is defined here"},
        {"file_path": "shop/cart.py", "line": None, "reason": "line outside the file"},
    ]
    assert any("2 related location(s)" in w for w in result["warnings"])
    assert "Diagnostic to explain: id=d1" in stub.requests[0].user
    assert api.get("/api/v1/history?event_type=ai.explained").json()["total"] == 1


@pytest.mark.parametrize(
    ("changes", "status", "code"),
    [
        ({"diagnostic": None}, 422, "validation_error"),
        ({"diagnostic": {**UNDEFINED_TOTAL, "line": 40, "end_line": 40}}, 422, "invalid_range"),
        ({"diagnostic": {**UNDEFINED_TOTAL, "end_line": 4}}, 422, "invalid_range"),
        ({"diagnostic": {**UNDEFINED_TOTAL, "line": 0}}, 422, "validation_error"),
        ({"diagnostic": UNDEFINED_TOTAL, "file_path": "../outside.py"}, 422, "validation_error"),
        ({"diagnostic": UNDEFINED_TOTAL, "file_path": "/etc/passwd"}, 422, "validation_error"),
        ({"diagnostic": UNDEFINED_TOTAL, "unexpected": True}, 422, "validation_error"),
    ],
)
def test_invalid_explanation_requests(
    api: TestClient, stub: StubProvider, changes: dict[str, Any], status: int, code: str
) -> None:
    request = body(**changes)
    if request.get("diagnostic") is None:
        request.pop("diagnostic")
    response = api.post("/api/v1/ai/explain", json=request)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert stub.requests == []  # rejected before any provider call


# --- Module 8: fix suggestions -----------------------------------------------------------


def test_fix_suggestion_is_a_proposal_only(api: TestClient, stub: StubProvider, shop: dict[str, Any]) -> None:
    stub.answers.append(
        fix({"start_line": 4, "end_line": 4, "replacement": "    total = 0\n    for item in items:"})
    )
    cart = shop["files"]["shop/cart.py"]
    base = f"/api/v1/projects/{shop['id']}/files/{cart['id']}"
    versions_before = api.get(f"{base}/versions").json()["total"]

    response = api.post(
        "/api/v1/ai/fix-suggestion", json=body(project_id=shop["id"], diagnostic=UNDEFINED_TOTAL)
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "suggested"
    assert result["original_code"] == CART
    assert result["suggested_code"] == CART.replace("    for item", "    total = 0\n    for item", 1)
    assert "+    total = 0\n" in result["diff"]
    assert result["diff"].startswith("--- a/shop/cart.py\n+++ b/shop/cart.py")
    assert result["edits"] == [
        {
            "file_path": "shop/cart.py",
            "start_line": 4,
            "start_column": 1,
            "end_line": 5,
            "end_column": 1,
            "replacement_text": "    total = 0\n    for item in items:\n",
        }
    ]
    assert len(result["original_hash"]) == 64

    # Nothing was written: same content, no new version, no file history event.
    assert api.get(base).json()["content"] == CART
    assert api.get(f"{base}/versions").json()["total"] == versions_before
    types = [e["event_type"] for e in api.get("/api/v1/history").json()["items"]]
    assert types[0] == "ai.fix_suggested"
    assert types.count("file.updated") == 0


@pytest.mark.parametrize(
    "edits",
    [
        [
            {"start_line": 2, "end_line": 4, "replacement": "a"},
            {"start_line": 4, "end_line": 5, "replacement": "b"},
        ],
        [{"start_line": 40, "end_line": 41, "replacement": "x"}],
        [{"start_line": 1, "end_line": 6, "replacement": ""}],  # would delete the whole file
    ],
)
def test_invalid_patches_are_discarded(
    api: TestClient, stub: StubProvider, edits: list[dict[str, Any]]
) -> None:
    stub.answers.append(fix(*edits))
    result = api.post("/api/v1/ai/fix-suggestion", json=body(diagnostic=UNDEFINED_TOTAL)).json()
    assert result["status"] == "no_suggestion"
    assert result["suggested_code"] == CART
    assert result["diff"] == ""
    assert result["edits"] == []
    assert any("failed validation" in w for w in result["warnings"])


def test_no_useful_suggestion(api: TestClient, stub: StubProvider) -> None:
    stub.answers.append(fix(no_change_reason="The fix needs a change in another file."))
    result = api.post("/api/v1/ai/fix-suggestion", json=body(diagnostic=UNDEFINED_TOTAL)).json()
    assert result["status"] == "no_suggestion"
    assert "another file" in " ".join(result["warnings"])


def test_fix_requires_a_target(api: TestClient, stub: StubProvider) -> None:
    assert api.post("/api/v1/ai/fix-suggestion", json=body()).status_code == 422
    stub.answers.append(fix({"start_line": 6, "end_line": 6, "replacement": "    return total or 0"}))
    result = api.post("/api/v1/ai/fix-suggestion", json=body(instruction="Return 0 for an empty cart")).json()
    assert result["status"] == "suggested"
    assert "Developer's request: Return 0 for an empty cart" in stub.requests[0].user


# --- provider failures, ownership, limits ------------------------------------------------


def test_malformed_and_failed_provider_answers(api: TestClient, stub: StubProvider) -> None:
    stub.answers += [
        {"summary": 1, "findings": "nope"},
        AITimeoutError(),
        AIRateLimitedError("The AI provider is rate limiting requests."),
        AIUnavailableError("The AI provider could not be reached."),
    ]
    expected = [
        (502, "ai_malformed_response"),
        (504, "ai_timeout"),
        (429, "ai_rate_limited"),
        (503, "ai_unavailable"),
    ]
    for status, code in expected:
        response = api.post("/api/v1/ai/analyze", json=body())
        assert (response.status_code, response.json()["error"]["code"]) == (status, code)


def test_ai_respects_project_ownership(
    api: TestClient, other_user: TestClient, stub: StubProvider, shop: dict[str, Any]
) -> None:
    for path in ("analyze", "explain", "fix-suggestion"):
        extra = {} if path == "analyze" else {"diagnostic": UNDEFINED_TOTAL}
        response = other_user.post(f"/api/v1/ai/{path}", json=body(project_id=shop["id"], **extra))
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "project_not_found"
    outside = api.post("/api/v1/ai/analyze", json=body(project_id=shop["id"], file_path="shop/missing.py"))
    assert outside.status_code == 404
    assert outside.json()["error"]["code"] == "file_not_found"
    assert stub.requests == []


def test_ai_requests_are_rate_limited_per_user(
    database_url: str, signed_in: Callable[[FastAPI], TestClient]
) -> None:
    app = build_app(database_url=database_url)
    provider = StubProvider(answers=[analysis(), analysis(), analysis()])
    app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url, ai_max_requests=2), provider=provider
    )
    client = signed_in(app)
    assert client.post("/api/v1/ai/analyze", json=body()).status_code == 200
    assert client.post("/api/v1/ai/analyze", json=body()).status_code == 200
    limited = client.post("/api/v1/ai/analyze", json=body())
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "too_many_ai_requests"
    assert int(limited.headers["Retry-After"]) > 0
    assert len(provider.requests) == 2


def test_fix_suggestions_refuse_oversized_files(api: TestClient, stub: StubProvider) -> None:
    code = "x = 1\n" * 20_000
    response = api.post("/api/v1/ai/fix-suggestion", json=body(code=code, diagnostics=[], instruction="tidy"))
    assert response.status_code == 413
    assert stub.requests == []
