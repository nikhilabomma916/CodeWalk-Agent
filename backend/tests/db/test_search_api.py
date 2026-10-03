"""Project search, snippets, and context (Module 9) against real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

FILES = {
    "src/auth/service.py": (
        "import hashlib\n"
        "\n"
        "from src.db.connection import get_connection\n"
        "\n"
        "\n"
        "class UserService:\n"
        "    def authenticate_user(self, name, password):\n"
        "        conn = get_connection()\n"
        "        return check_password(password)\n"
        "\n"
        "\n"
        "def check_password(password):\n"
        "    return hashlib.sha256(password.encode()).hexdigest()\n"
    ),
    "src/auth/routes.py": (
        "from src.auth.service import UserService\n"
        "\n"
        "\n"
        "def login(request):\n"
        "    service = UserService()\n"
        "    return service.authenticate_user(request.name, request.password)\n"
    ),
    "src/db/connection.py": (
        'def get_connection():\n    """Open the database connection."""\n    return None\n'
    ),
    "web/api.ts": (
        "export function calculateTotal(items: number[]): number {\n"
        "  return items.reduce((a, b) => a + b, 0);\n}\n"
    ),
    "README.md": "# Auth service\nThe authentication middleware lives in src/auth.\n",
    "node_modules/lib/index.js": "export function authenticate_user() {}\n",
}


@pytest.fixture
def project(api: TestClient) -> dict[str, Any]:
    created = api.post("/api/v1/projects", json={"name": "Auth"}).json()
    ids = {}
    for path, content in FILES.items():
        response = api.post(
            f"/api/v1/projects/{created['id']}/files", json={"path": path, "content": content}
        )
        assert response.status_code == 201, response.text
        ids[path] = response.json()["file"]["id"]
    return {"id": created["id"], "files": ids}


def search(api: TestClient, project_id: str, query: str, **extra: Any) -> dict[str, Any]:
    response = api.post(f"/api/v1/projects/{project_id}/search", json={"query": query, **extra})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_exact_symbol_ranks_first(api: TestClient, project: dict[str, Any]) -> None:
    result = search(api, project["id"], "UserService")
    top = result["results"][0]
    assert (top["file_path"], top["symbol_name"], top["symbol_type"], top["line"]) == (
        "src/auth/service.py",
        "UserService",
        "class",
        6,
    )
    assert top["match_type"] == "symbol_exact"
    assert top["score"] == 100
    assert top["score_details"] == {"base": 100, "coverage": 1.0, "context_bonus": 0}
    assert "authenticate_user" in " ".join(top["related_symbols"])
    assert top["snippet"]["lines"][0] == "class UserService:"
    kinds = {(r["file_path"], r["match_type"]) for r in result["results"]}
    assert ("src/auth/routes.py", "import") in kinds
    assert ("src/auth/routes.py", "identifier") in kinds
    assert "symbol_exact=100" in result["ranking"]
    assert result["indexed_files"] == 5  # node_modules is never indexed


def test_methods_identifiers_and_ignored_files(api: TestClient, project: dict[str, Any]) -> None:
    result = search(api, project["id"], "authenticate_user")
    top = result["results"][0]
    assert (top["symbol_name"], top["symbol_type"], top["qualified_name"]) == (
        "authenticate_user",
        "method",
        "UserService.authenticate_user",
    )
    assert all(not r["file_path"].startswith("node_modules") for r in result["results"])
    identifier = next(r for r in result["results"] if r["match_type"] == "identifier")
    assert (identifier["file_path"], identifier["line"], identifier["column"]) == (
        "src/auth/routes.py",
        6,
        20,
    )


def test_cross_language_and_multi_word_queries(api: TestClient, project: dict[str, Any]) -> None:
    ts = search(api, project["id"], "calculate_total")["results"][0]
    assert (ts["file_path"], ts["symbol_name"], ts["language"], ts["match_type"]) == (
        "web/api.ts",
        "calculateTotal",
        "typescript",
        "symbol_exact",
    )
    phrase = search(api, project["id"], "database connection")
    types = {(r["file_path"], r["match_type"]) for r in phrase["results"]}
    assert ("src/db/connection.py", "file_path") in types
    assert ("src/db/connection.py", "text") in types  # the docstring line
    assert ("src/db/connection.py", "symbol_tokens") in types  # get_connection
    text = search(api, project["id"], "authentication middleware")["results"][0]
    assert (text["file_path"], text["match_type"], text["line"]) == ("README.md", "text", 2)


def test_file_names(api: TestClient, project: dict[str, Any]) -> None:
    top = search(api, project["id"], "routes")["results"][0]
    assert (top["file_path"], top["match_type"], top["line"]) == ("src/auth/routes.py", "file_name", None)


def test_filters_and_limits(api: TestClient, project: dict[str, Any]) -> None:
    pid = project["id"]
    python_only = search(api, pid, "total", filters={"language": "python"})
    assert all(r["language"] == "python" for r in python_only["results"])
    functions = search(api, pid, "password", filters={"symbol_type": "function"})
    assert functions["results"]
    assert all(r["symbol_type"] == "function" for r in functions["results"])
    assert [r["symbol_name"] for r in functions["results"]] == ["check_password"]
    in_db = search(api, pid, "connection", filters={"path_prefix": "src/db"})
    assert {r["file_path"] for r in in_db["results"]} == {"src/db/connection.py"}
    text_only = search(api, pid, "UserService", filters={"match_types": ["identifier"]})
    assert {r["match_type"] for r in text_only["results"]} == {"identifier"}

    limited = search(api, pid, "UserService", limit=1)
    assert len(limited["results"]) == 1
    assert limited["truncated"] is True
    assert limited["total"] > 1

    for bad in (
        {"query": ""},
        {"query": "x", "limit": 0},
        {"query": "x", "limit": 101},
        {"query": "x", "extra": 1},
    ):
        assert api.post(f"/api/v1/projects/{pid}/search", json=bad).status_code == 422


def test_current_file_context_bonus(api: TestClient, project: dict[str, Any]) -> None:
    pid = project["id"]
    plain = search(api, pid, "check_password")["results"][0]
    assert plain["score"] == 100
    related = search(api, pid, "get_connection", current_file="src/auth/routes.py")["results"]
    # routes.py imports service.py, which imports connection.py: only direct relations get the bonus.
    assert related[0]["file_path"] == "src/db/connection.py"
    assert related[0]["score_details"]["context_bonus"] == 0
    in_current = search(api, pid, "check_password", current_file="src/auth/service.py")["results"][0]
    assert in_current["score_details"]["context_bonus"] == 15
    from_importer = search(api, pid, "UserService", current_file="src/auth/routes.py")["results"][0]
    assert from_importer["file_path"] == "src/auth/service.py"
    assert from_importer["score_details"]["context_bonus"] == 10
    missing = api.post(f"/api/v1/projects/{pid}/search", json={"query": "x", "current_file": "nope.py"})
    assert missing.status_code == 404


def test_snippets_are_bounded(api: TestClient, project: dict[str, Any]) -> None:
    pid = project["id"]
    long_body = "".join(f"    step_{i} = {i}  # {'x' * 400}\n" for i in range(40))
    api.post(
        f"/api/v1/projects/{pid}/files",
        json={"path": "src/long.py", "content": f"def long_function():\n{long_body}"},
    )
    top = search(api, pid, "long_function")["results"][0]
    snippet = top["snippet"]
    assert len(snippet["lines"]) == 12
    assert snippet["truncated"] is True
    assert all(len(line) <= 301 for line in snippet["lines"])

    ok = api.post(
        f"/api/v1/projects/{pid}/snippet",
        json={"file_path": "src/auth/service.py", "line": 7, "before": 1, "after": 2},
    )
    assert ok.json() == {
        "file_path": "src/auth/service.py",
        "start_line": 6,
        "end_line": 9,
        "lines": [
            "class UserService:",
            "    def authenticate_user(self, name, password):",
            "        conn = get_connection()",
            "        return check_password(password)",
        ],
        "truncated": False,
    }
    assert (
        api.post(
            f"/api/v1/projects/{pid}/snippet", json={"file_path": "src/auth/service.py", "line": 500}
        ).status_code
        == 404
    )
    assert (
        api.post(f"/api/v1/projects/{pid}/snippet", json={"file_path": "nope.py", "line": 1}).status_code
        == 404
    )
    for bad in ("../../etc/passwd", "/etc/passwd", "C:/Windows/win.ini", "node_modules/../../x"):
        assert (
            api.post(f"/api/v1/projects/{pid}/snippet", json={"file_path": bad, "line": 1}).status_code == 422
        )
    too_wide = api.post(
        f"/api/v1/projects/{pid}/snippet", json={"file_path": "src/auth/service.py", "line": 1, "after": 500}
    )
    assert too_wide.status_code == 422
    ignored = api.post(
        f"/api/v1/projects/{pid}/snippet", json={"file_path": "node_modules/lib/index.js", "line": 1}
    )
    assert ignored.status_code == 404


def test_context_builder(api: TestClient, project: dict[str, Any]) -> None:
    diagnostic = {
        "id": "d1",
        "severity": "error",
        "message": "Undefined name `get_connection`",
        "source": "ruff",
        "line": 8,
        "column": 16,
        "end_line": 8,
        "end_column": 30,
    }
    response = api.post(
        f"/api/v1/projects/{project['id']}/context",
        json={
            "current_file": "src/auth/service.py",
            "line": 8,
            "diagnostics": [diagnostic],
            "query": "login",
        },
    )
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["containing_symbol"]["qualified_name"] == "UserService.authenticate_user"
    roles = {(f["file_path"], f["role"]) for f in context["files"]}
    assert ("src/db/connection.py", "imported") in roles
    assert ("src/auth/routes.py", "importer") in roles
    reasons = {(s["file_path"], s["reason"]) for s in context["snippets"]}
    assert ("src/db/connection.py", "defines 'get_connection' (named in a diagnostic)") in reasons
    assert ("src/auth/routes.py", "matches 'login'") in reasons
    assert ("src/auth/routes.py", "imports the current file") in reasons
    assert {s["qualified_name"] for s in context["symbols"]} >= {"get_connection"}
    assert {(r["source"], r["target"]) for r in context["relationships"]} == {
        ("src/auth/service.py", "src/db/connection.py"),
        ("src/auth/routes.py", "src/auth/service.py"),
    }
    assert context["metadata"]["strategy"].startswith("deterministic")
    assert context["metadata"]["chars"] <= context["metadata"]["max_chars"]
    assert all(s["file_path"] != "src/auth/service.py" for s in context["snippets"])


def test_index_follows_file_changes(api: TestClient, project: dict[str, Any]) -> None:
    pid = project["id"]
    assert search(api, pid, "brand_new_helper")["total"] == 0
    file_id = project["files"]["src/db/connection.py"]
    api.patch(
        f"/api/v1/projects/{pid}/files/{file_id}",
        json={"content": FILES["src/db/connection.py"] + "\n\ndef brand_new_helper():\n    return 1\n"},
    )
    top = search(api, pid, "brand_new_helper")["results"][0]
    assert (top["file_path"], top["line"]) == ("src/db/connection.py", 6)


def test_search_respects_ownership(
    api: TestClient, other_user: TestClient, anonymous: TestClient, project: dict[str, Any]
) -> None:
    pid = project["id"]
    for path, payload in (
        ("search", {"query": "UserService"}),
        ("snippet", {"file_path": "src/auth/service.py", "line": 1}),
        ("context", {"current_file": "src/auth/service.py"}),
    ):
        stolen = other_user.post(f"/api/v1/projects/{pid}/{path}", json=payload)
        assert stolen.status_code == 404, path
        assert "UserService" not in stolen.text
        assert anonymous.post(f"/api/v1/projects/{pid}/{path}", json=payload).status_code == 401
