"""Semantic retrieval (Module 10) against real PostgreSQL + pgvector, with a stub embedding provider.

The stub (tests/embedding_stub.py) is a hashed bag of words, not a real model: these
tests check CodeWalk's own behavior (availability states, chunk storage, incremental
indexing, pgvector queries, filters, fusion, context, AI integration, authorization),
not retrieval quality. The real Voyage integration is covered by the mocked-HTTP
provider tests and the optional live smoke test.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import CodeChunk
from app.services.ai.service import AIService
from app.services.retrieval.base import EmbeddingUnavailableError
from app.services.retrieval.service import RetrievalService
from tests.ai_stub import StubProvider, explanation
from tests.conftest import make_settings
from tests.embedding_stub import StubEmbeddingProvider

FILES = {
    "src/auth/service.py": (
        "import hashlib\n"
        "\n"
        "\n"
        "class UserService:\n"
        "    def __init__(self, repo):\n"
        "        self.repo = repo\n"
        "\n"
        "    def authenticate_user(self, email, password):\n"
        "        user = self.repo.find_user(email)\n"
        "        digest = hashlib.sha256(password.encode()).hexdigest()\n"
        "        return user is not None and user.password_hash == digest\n"
    ),
    "src/auth/routes.py": (
        "from src.auth.service import UserService\n"
        "\n"
        "\n"
        "def login(request, service: UserService):\n"
        "    return service.authenticate_user(request.email, request.password)\n"
    ),
    "src/billing/invoice.py": (
        "def compute_invoice_total(lines):\n"
        "    total = 0\n"
        "    for line in lines:\n"
        "        total += line.price * line.quantity\n"
        "    return total\n"
    ),
    "src/billing/tax.py": "def apply_sales_tax(amount, rate):\n    return amount * (1 + rate)\n",
    "docs/README.md": "# Billing\nInvoices are totalled per line, then sales tax is applied.\n",
    "node_modules/lib/index.js": "export function verifyUserPassword(user, password) { return true }\n",
}
INDEXABLE = len(FILES) - 1  # node_modules is never indexed


@pytest.fixture
def project(api: TestClient) -> dict[str, Any]:
    created = api.post("/api/v1/projects", json={"name": "Retrieval"}).json()
    ids = {}
    for path, content in FILES.items():
        response = api.post(
            f"/api/v1/projects/{created['id']}/files", json={"path": path, "content": content}
        )
        assert response.status_code == 201, response.text
        ids[path] = response.json()["file"]["id"]
    return {"id": created["id"], "files": ids}


@pytest.fixture
def embeddings(db_app: FastAPI, database_url: str) -> StubEmbeddingProvider:
    stub = StubEmbeddingProvider()
    db_app.state.retrieval_service = RetrievalService(
        make_settings(rag_enabled=True, database_url=database_url), provider=stub
    )
    return stub


def index(api: TestClient, pid: str) -> dict[str, Any]:
    response = api.post(f"/api/v1/projects/{pid}/rag/index")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def search(api: TestClient, pid: str, query: str, **extra: Any) -> dict[str, Any]:
    response = api.post(f"/api/v1/projects/{pid}/search", json={"query": query, **extra})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def chunk_count(engine: Engine, **where: Any) -> int:
    with Session(engine) as session:
        statement = select(func.count()).select_from(CodeChunk)
        for column, value in where.items():
            statement = statement.where(getattr(CodeChunk, column) == value)
        return int(session.execute(statement).scalar_one())


# --- disabled / not configured -------------------------------------------------------------


def test_status_disabled_by_default_and_safe(api: TestClient, anonymous: TestClient) -> None:
    status = api.get("/api/v1/rag/status").json()
    assert (status["enabled"], status["configured"], status["available"]) == (False, False, False)
    assert status["dimensions"] == 1024
    assert "RAG_ENABLED" in status["detail"]
    assert anonymous.get("/api/v1/rag/status").status_code == 401


def test_disabled_retrieval_keeps_deterministic_search(api: TestClient, project: dict[str, Any]) -> None:
    pid = project["id"]
    deterministic = search(api, pid, "authenticate_user")
    hybrid = search(api, pid, "authenticate_user", mode="hybrid")
    assert hybrid["mode"] == "hybrid"
    assert hybrid["mode_used"] == "deterministic"
    assert any("turned off" in w for w in hybrid["warnings"])
    assert hybrid["results"] == deterministic["results"]
    assert deterministic["mode_used"] == "deterministic"
    assert deterministic["warnings"] == []

    refused = api.post(f"/api/v1/projects/{pid}/rag/index")
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "rag_disabled"
    state = api.get(f"/api/v1/projects/{pid}/rag/index").json()
    assert state["available"] is False
    assert (state["indexable_files"], state["indexed_files"]) == (INDEXABLE, 0)


def test_enabled_without_key_is_not_configured(
    db_app: FastAPI,
    database_url: str,
    api: TestClient,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    db_app.state.retrieval_service = RetrievalService(
        make_settings(rag_enabled=True, database_url=database_url)
    )
    status = api.get("/api/v1/rag/status").json()
    assert (status["enabled"], status["configured"], status["provider"], status["model"]) == (
        True,
        False,
        "voyage",
        "voyage-code-4",
    )
    assert "VOYAGE_API_KEY" in status["detail"]
    refused = api.post(f"/api/v1/projects/{project['id']}/rag/index")
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "rag_not_configured"
    assert search(api, project["id"], "login", mode="semantic")["mode_used"] == "deterministic"


# --- indexing ------------------------------------------------------------------------------


def test_indexing_stores_chunks_for_searchable_files_only(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider, engine: Engine
) -> None:
    pid = project["id"]
    run = index(api, pid)
    assert run["files_indexed"] == INDEXABLE
    assert run["chunks_embedded"] == chunk_count(engine, project_id=project["id"]) > 0
    assert run["chunks_reused"] == 0
    assert run["remaining_files"] == 0
    assert run["status"]["indexed_files"] == INDEXABLE
    assert run["status"]["model"] == "stub-hashed-bag-of-words"
    assert chunk_count(engine, file_id=project["files"]["node_modules/lib/index.js"]) == 0
    documents = embeddings.texts(embeddings.calls[0][0])
    assert all(t.startswith("File: ") for t in documents)
    assert {c[0].value for c in embeddings.calls} == {"document"}

    with Session(engine) as session:
        stored = session.execute(
            select(CodeChunk.symbol_name, CodeChunk.start_line, CodeChunk.end_line).where(
                CodeChunk.file_id == project["files"]["src/auth/service.py"]
            )
        ).all()
    assert ("UserService.authenticate_user", 8, 11) in stored

    again = index(api, pid)
    assert (again["files_indexed"], again["chunks_embedded"]) == (0, 0)
    assert len(embeddings.calls) == 1  # nothing re-embedded


def test_reindexing_reuses_unchanged_chunks(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider, engine: Engine
) -> None:
    pid = project["id"]
    index(api, pid)
    before = chunk_count(engine, file_id=project["files"]["src/auth/service.py"])
    api.patch(
        f"/api/v1/projects/{pid}/files/{project['files']['src/auth/service.py']}",
        json={"content": FILES["src/auth/service.py"] + "\n\ndef reset_password(user):\n    user.reset()\n"},
    )
    stale = api.get(f"/api/v1/projects/{pid}/rag/index").json()
    assert (stale["indexed_files"], stale["stale_files"]) == (INDEXABLE - 1, 1)

    run = index(api, pid)
    assert run["files_indexed"] == 1
    assert run["chunks_embedded"] == 1  # only the new function
    assert run["chunks_reused"] == before
    assert embeddings.calls[-1][1][0].endswith("def reset_password(user):\n    user.reset()")
    assert chunk_count(engine, file_id=project["files"]["src/auth/service.py"]) == before + 1


def test_index_runs_are_bounded_and_rate_limited(
    db_app: FastAPI, database_url: str, api: TestClient, project: dict[str, Any]
) -> None:
    db_app.state.retrieval_service = RetrievalService(
        make_settings(
            rag_enabled=True, database_url=database_url, rag_max_chunks_per_run=1, rag_max_index_runs=2
        ),
        provider=StubEmbeddingProvider(),
    )
    first = index(api, project["id"])
    assert first["files_indexed"] == 1
    assert first["remaining_files"] == INDEXABLE - 1
    index(api, project["id"])
    limited = api.post(f"/api/v1/projects/{project['id']}/rag/index")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "too_many_index_runs"
    assert "Retry-After" in limited.headers


def test_provider_failure_during_indexing_writes_nothing(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider, engine: Engine
) -> None:
    embeddings.errors.append(EmbeddingUnavailableError("The embedding provider is temporarily unavailable."))
    failed = api.post(f"/api/v1/projects/{project['id']}/rag/index")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "rag_unavailable"
    assert chunk_count(engine, project_id=project["id"]) == 0


# --- semantic and hybrid search ------------------------------------------------------------


def test_semantic_search_returns_real_locations(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider
) -> None:
    pid = project["id"]
    index(api, pid)
    found = search(api, pid, "check a user's password hash", mode="semantic")
    assert found["mode_used"] == "semantic"
    assert "cosine similarity" in found["ranking"]
    top = found["results"][0]
    assert (top["file_path"], top["line"], top["end_line"]) == ("src/auth/service.py", 8, 11)
    assert top["match_type"] == "semantic"
    assert top["qualified_name"] == "UserService.authenticate_user"
    assert top["symbol_name"] == "authenticate_user"
    assert top["symbol_type"] == "method"
    assert top["score"] == top["semantic_similarity"]
    assert 0 < top["semantic_similarity"] <= 1
    assert top["score_details"] is None
    assert top["snippet"]["lines"][0].strip().startswith("def authenticate_user")
    similarities = [r["semantic_similarity"] for r in found["results"]]
    assert similarities == sorted(similarities, reverse=True)
    assert all(not r["file_path"].startswith("node_modules/") for r in found["results"])
    assert embeddings.calls[-1][0].value == "query"


def test_semantic_filters(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider
) -> None:
    pid = project["id"]
    index(api, pid)
    billing = search(api, pid, "total", mode="semantic", filters={"path_prefix": "src/billing"})
    assert billing["results"]
    assert all(r["file_path"].startswith("src/billing/") for r in billing["results"])
    markdown = search(api, pid, "invoices tax", mode="semantic", filters={"language": "markdown"})
    assert {r["file_path"] for r in markdown["results"]} == {"docs/README.md"}
    methods = search(api, pid, "user", mode="semantic", filters={"symbol_type": "method"})
    assert methods["results"]
    assert {r["symbol_type"] for r in methods["results"]} == {"method"}
    excluded = search(api, pid, "user", mode="semantic", filters={"match_types": ["symbol_exact"]})
    assert excluded["mode_used"] == "deterministic"


def test_hybrid_fuses_both_lists(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider
) -> None:
    pid = project["id"]
    index(api, pid)
    hybrid = search(api, pid, "authenticate_user", mode="hybrid")
    assert hybrid["mode_used"] == "hybrid"
    assert "reciprocal rank fusion" in hybrid["ranking"]
    top = hybrid["results"][0]
    # Found by both lists: the exact symbol match and the most similar chunk are the same method.
    assert (top["file_path"], top["line"]) == ("src/auth/service.py", 8)
    assert top["match_type"] == "symbol_exact"
    assert top["score_details"]["base"] == 100
    assert top["fusion"]["deterministic_rank"] == 1
    assert top["fusion"]["semantic_rank"] is not None
    assert top["score"] == top["fusion"]["rrf_score"]
    assert top["semantic_similarity"] is not None
    scores = [r["score"] for r in hybrid["results"]]
    assert scores == sorted(scores, reverse=True)
    assert any(r["fusion"]["deterministic_rank"] is None for r in hybrid["results"])  # semantic-only matches
    keys = [(r["file_path"], r["line"], r["match_type"]) for r in hybrid["results"]]
    assert len(keys) == len(set(keys))


def test_stale_chunks_are_never_returned(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider
) -> None:
    pid = project["id"]
    index(api, pid)
    api.patch(
        f"/api/v1/projects/{pid}/files/{project['files']['src/billing/invoice.py']}",
        json={"content": "\n\n\n" + FILES["src/billing/invoice.py"]},  # every line moved down
    )
    found = search(api, pid, "invoice total price quantity", mode="semantic")
    assert all(r["file_path"] != "src/billing/invoice.py" for r in found["results"])
    assert any("changed since the last indexing" in w for w in found["warnings"])
    index(api, pid)
    top = search(api, pid, "invoice total price quantity", mode="semantic")["results"][0]
    assert (top["file_path"], top["line"]) == ("src/billing/invoice.py", 4)


def test_search_falls_back_when_the_provider_fails(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider
) -> None:
    pid = project["id"]
    index(api, pid)
    embeddings.errors.append(EmbeddingUnavailableError("The embedding provider could not be reached."))
    result = search(api, pid, "authenticate_user", mode="hybrid")
    assert result["mode_used"] == "deterministic"
    assert any(
        w.startswith("Semantic retrieval failed: The embedding provider could not be reached.")
        for w in result["warnings"]
    )
    assert result["results"][0]["match_type"] == "symbol_exact"


def test_unindexed_project_says_so(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider
) -> None:
    result = search(api, project["id"], "password", mode="semantic")
    assert result["mode_used"] == "semantic"
    assert result["results"] == []
    assert any("no semantic index yet" in w for w in result["warnings"])


# --- ownership -----------------------------------------------------------------------------


def test_retrieval_respects_ownership(
    api: TestClient,
    other_user: TestClient,
    anonymous: TestClient,
    project: dict[str, Any],
    embeddings: StubEmbeddingProvider,
) -> None:
    pid = project["id"]
    index(api, pid)
    calls = len(embeddings.calls)
    for method, path, payload in (
        ("post", f"/api/v1/projects/{pid}/rag/index", None),
        ("get", f"/api/v1/projects/{pid}/rag/index", None),
        ("post", f"/api/v1/projects/{pid}/search", {"query": "password", "mode": "hybrid"}),
    ):
        stolen = getattr(other_user, method)(path, **({"json": payload} if payload else {}))
        assert stolen.status_code == 404, path
        assert "authenticate" not in stolen.text
        assert getattr(anonymous, method)(path, **({"json": payload} if payload else {})).status_code == 401
    assert len(embeddings.calls) == calls  # nothing embedded for anyone else

    # Another user's indexed project with similar code never shows up in alice's results.
    theirs = other_user.post("/api/v1/projects", json={"name": "Theirs"}).json()
    other_user.post(
        f"/api/v1/projects/{theirs['id']}/files",
        json={"path": "src/their_secret_auth.py", "content": FILES["src/auth/service.py"]},
    )
    assert other_user.post(f"/api/v1/projects/{theirs['id']}/rag/index").status_code == 200
    mine = search(api, pid, "authenticate user password hash", mode="semantic", limit=100)
    assert all(r["file_path"] != "src/their_secret_auth.py" for r in mine["results"])


def test_chunks_are_deleted_with_their_project(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider, engine: Engine
) -> None:
    index(api, project["id"])
    assert chunk_count(engine, project_id=project["id"]) > 0
    assert api.delete(f"/api/v1/projects/{project['id']}").status_code == 204
    assert chunk_count(engine, project_id=project["id"]) == 0


# --- context and AI ------------------------------------------------------------------------

UNDEFINED = {
    "id": "d1",
    "severity": "error",
    "message": "Undefined name `verify_password`",
    "source": "ruff",
    "code": "F821",
    "category": "lint",
    "line": 5,
    "column": 12,
    "end_line": 5,
    "end_column": 27,
}


def test_context_adds_semantic_matches_after_deterministic_ones(
    api: TestClient, project: dict[str, Any], embeddings: StubEmbeddingProvider
) -> None:
    pid = project["id"]
    body = {"current_file": "src/auth/routes.py", "line": 5, "diagnostics": [UNDEFINED], "query": "password"}
    before = api.post(f"/api/v1/projects/{pid}/context", json=body).json()
    assert before["metadata"]["semantic"]["used"] is False  # nothing indexed yet

    index(api, pid)
    context = api.post(f"/api/v1/projects/{pid}/context", json=body).json()
    reasons = [s["reason"] for s in context["snippets"]]
    semantic = [r for r in reasons if r.startswith("semantically similar")]
    assert semantic, reasons
    first_semantic = reasons.index(semantic[0])
    assert all(not r.startswith("semantically") for r in reasons[:first_semantic])
    assert context["metadata"]["semantic"]["used"] is True
    assert "semantic (stub-hashed-bag-of-words embeddings)" in context["metadata"]["strategy"]
    assert all(s["file_path"] != "src/auth/routes.py" for s in context["snippets"])
    listed = {f["file_path"] for f in context["files"]}
    assert {s["file_path"] for s in context["snippets"]} <= listed


def test_context_without_retrieval_is_deterministic(api: TestClient, project: dict[str, Any]) -> None:
    context = api.post(
        f"/api/v1/projects/{project['id']}/context", json={"current_file": "src/auth/routes.py", "line": 5}
    ).json()
    assert context["metadata"]["strategy"] == "deterministic (symbols, imports, text)"
    assert context["metadata"]["semantic"]["used"] is False


def test_ai_explanation_receives_semantic_context(
    db_app: FastAPI,
    database_url: str,
    api: TestClient,
    project: dict[str, Any],
    embeddings: StubEmbeddingProvider,
) -> None:
    ai = StubProvider(answers=[explanation()])
    db_app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url), provider=ai
    )
    index(api, project["id"])
    code = FILES["src/auth/routes.py"].replace("service.authenticate_user(", "verify_password(")
    response = api.post(
        "/api/v1/ai/explain",
        json={
            "project_id": project["id"],
            "code": code,
            "language": "python",
            "file_path": "src/auth/routes.py",
            "diagnostic": UNDEFINED,
            "diagnostics": [UNDEFINED],
        },
    )
    assert response.status_code == 200, response.text
    summary = response.json()["context"]
    assert summary["semantic_snippet_count"] >= 1
    assert 'reason="semantically similar' in ai.requests[0].user


def test_migration_enables_pgvector_and_hnsw(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        indexdef: str = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_code_chunks_embedding_hnsw'")
        ).scalar_one()
    assert "USING hnsw" in indexdef
    assert "vector_cosine_ops" in indexdef


# --- database failures in the vector query ------------------------------------------------


class _BrokenQueryVectors(StubEmbeddingProvider):
    """Documents embed normally; queries come back 3-dimensional, so PostgreSQL itself rejects the
    similarity comparison ("different vector dimensions"): a real database-level failure."""

    def embed(self, texts: list[str], input_type: Any) -> Any:
        result = super().embed(texts, input_type)
        if input_type.value == "query":
            result.vectors = [[1.0, 0.0, 0.0] for _ in texts]
        return result


@pytest.fixture
def broken_queries(db_app: FastAPI, database_url: str) -> _BrokenQueryVectors:
    stub = _BrokenQueryVectors()
    db_app.state.retrieval_service = RetrievalService(
        make_settings(rag_enabled=True, database_url=database_url), provider=stub
    )
    return stub


def test_database_failure_in_semantic_query_falls_back(
    api: TestClient, project: dict[str, Any], broken_queries: _BrokenQueryVectors
) -> None:
    pid = project["id"]
    index(api, pid)
    result = search(api, pid, "authenticate_user", mode="hybrid")
    assert result["mode_used"] == "deterministic"
    assert "Semantic retrieval failed: The semantic index could not be queried." in result["warnings"][0]
    assert result["results"][0]["match_type"] == "symbol_exact"
    assert all(r["match_type"] != "semantic" for r in result["results"])

    context = api.post(
        f"/api/v1/projects/{pid}/context", json={"current_file": "src/auth/routes.py", "line": 5}
    )
    assert context.status_code == 200
    assert context.json()["metadata"]["semantic"]["used"] is False
    assert api.get(f"/api/v1/projects/{pid}/rag/index").json()["indexed_files"] == INDEXABLE


def test_database_failure_in_semantic_context_keeps_the_ai_request_working(
    db_app: FastAPI,
    database_url: str,
    api: TestClient,
    project: dict[str, Any],
    broken_queries: _BrokenQueryVectors,
) -> None:
    ai = StubProvider(answers=[explanation()])
    db_app.state.ai_service = AIService(
        make_settings(ai_enabled=True, database_url=database_url), provider=ai
    )
    index(api, project["id"])
    code = FILES["src/auth/routes.py"].replace("service.authenticate_user(", "verify_password(")
    response = api.post(
        "/api/v1/ai/explain",
        json={
            "project_id": project["id"],
            "code": code,
            "language": "python",
            "file_path": "src/auth/routes.py",
            "diagnostic": UNDEFINED,
            "diagnostics": [UNDEFINED],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["context"]["semantic_snippet_count"] == 0
    assert any("Semantic context was not added" in w for w in body["warnings"])
    # The answer was still recorded: the request's transaction was not aborted by the failed query.
    history = api.get(f"/api/v1/projects/{project['id']}/analyses").json()
    assert any(item["analysis_type"] == "ai_explanation" for item in history["items"])
