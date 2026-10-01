from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import build_app


def test_analyze_valid_request(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analysis/code",
        json={"code": "import os\n", "language": "python", "file_path": "src/example.py"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["language"] == "python"
    assert body["file_path"] == "src/example.py"
    [diagnostic] = body["diagnostics"]
    assert diagnostic["code"] == "F401"
    assert diagnostic["file_path"] == "src/example.py"
    assert {
        "id",
        "severity",
        "message",
        "source",
        "category",
        "line",
        "column",
        "end_line",
        "end_column",
        "suggestion",
        "documentation_url",
        "fixable",
        "metadata",
    } <= diagnostic.keys()
    assert {c["kind"] for c in body["capabilities"]} >= {"syntax", "lint", "types"}
    assert body["analysis_duration_ms"] >= 0
    assert body["analysis_id"] is None  # real-time analysis is not persisted


def test_language_detected_from_path(client: TestClient) -> None:
    body = client.post("/api/v1/analysis/code", json={"code": "{", "file_path": "a.json"}).json()
    assert body["language"] == "json"
    assert body["diagnostics"][0]["severity"] == "error"


def test_missing_code_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/analysis/code", json={"language": "python"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["location"] == ["body", "code"]


def test_invalid_language_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/analysis/code", json={"code": "x", "language": "klingon"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/analysis/code", json={"code": "x", "execute": True})
    assert response.status_code == 422


def test_path_traversal_in_file_path_is_rejected(client: TestClient) -> None:
    for path in ("../../etc/passwd", "/etc/passwd", "C:\\Windows\\win.ini"):
        response = client.post("/api/v1/analysis/code", json={"code": "x", "file_path": path})
        assert response.status_code == 422, path


def test_malformed_json_body(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analysis/code", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_oversized_code_is_rejected(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(build_app(max_source_bytes=1000, max_request_body_bytes=10_000))
    response = client.post("/api/v1/analysis/code", json={"code": "x" * 2000, "language": "python"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "source_too_large"


def test_oversized_body_is_rejected_before_parsing(client_factory: Callable[[FastAPI], TestClient]) -> None:
    client = client_factory(build_app(max_source_bytes=1000, max_request_body_bytes=10_000))
    response = client.post("/api/v1/analysis/code", json={"code": "x" * 20_000})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_unsupported_language_response(client: TestClient) -> None:
    body = client.post("/api/v1/analysis/code", json={"code": "a: 1", "file_path": "c.yaml"}).json()
    assert body["success"] is True
    assert body["diagnostics"] == []
    assert {c["status"] for c in body["capabilities"]} == {"not_supported"}


def test_languages_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/analysis/languages")
    assert response.status_code == 200
    languages = {item["language"]: item for item in response.json()}
    assert {"python", "typescript", "json", "html", "css", "sql", "markdown", "java", "c", "cpp"} <= set(
        languages
    )
    assert languages["python"]["available"] is True


def test_persistence_endpoints_report_missing_database(client: TestClient) -> None:
    response = client.get("/api/v1/projects")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_not_configured"
