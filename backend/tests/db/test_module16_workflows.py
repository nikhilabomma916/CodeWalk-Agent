"""Module 16 end-to-end workflows over HTTP on real PostgreSQL (one request after another, as the UI
sends them).

Workflow A (normal coding) and Workflow C (security) run against the real application and database.
AI steps use the test-only stub model (tests/ai_stub.py) and semantic steps the test-only stub
embedder (tests/embedding_stub.py): they exercise CodeWalk's own behavior (prompting, validation,
proposals, approval, persistence, authorization), not a real provider, which needs credentials.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.ai.service import AIService
from app.services.retrieval.service import RetrievalService
from tests.ai_stub import StubProvider, explanation
from tests.conftest import build_app, make_settings
from tests.db.conftest import TEST_PASSWORD, register
from tests.embedding_stub import StubEmbeddingProvider

API = "/api/v1"
CART = "def cart_total(items):\n    for item in items:\n        total += item.price\n    return total\n"
PRICING = "def price_of(item):\n    return item.price\n"


def stub_app(database_url: str, workspace: Path) -> tuple[FastAPI, StubProvider]:
    app = build_app(
        database_url=database_url, workspace_root=str(workspace), ai_enabled=True, rag_enabled=True
    )
    stub = StubProvider()
    app.state.ai_service = AIService(make_settings(ai_enabled=True, database_url=database_url), provider=stub)
    app.state.retrieval_service = RetrievalService(
        make_settings(rag_enabled=True, database_url=database_url), provider=StubEmbeddingProvider()
    )
    return app, stub


def proposal(line_2: str) -> list[dict[str, Any]]:
    edits = [{"start_line": 2, "end_line": 2, "replacement": line_2}]
    return [
        {
            "status_message": "Proposing a fix",
            "action": "call_tool",
            "tool": "propose_fix",
            "arguments_json": json.dumps(
                {
                    "file_path": "shop/cart.py",
                    "summary": "Initialise total",
                    "explanation": "x",
                    "edits": edits,
                }
            ),
            "answer": None,
        },
        {
            "status_message": "Done",
            "action": "answer",
            "tool": None,
            "arguments_json": None,
            "answer": "Fixed.",
        },
    ]


def test_workflow_a_normal_coding(
    database_url: str, workspace: Path, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    app, stub = stub_app(database_url, workspace)
    client = client_factory(app)
    # 1. Login.
    register(client)
    assert client.post(f"{API}/auth/logout").status_code == 204
    assert client.get(f"{API}/auth/me").status_code == 401
    login = client.post(f"{API}/auth/login", json={"email": "alice@example.com", "password": TEST_PASSWORD})
    assert login.status_code == 200
    # 2. Open project.
    project = client.post(f"{API}/projects", json={"name": "Shop"}).json()
    pid = project["id"]
    assert client.get(f"{API}/projects/{pid}").status_code == 200
    client.post(f"{API}/projects/{pid}/files", json={"path": "shop/pricing.py", "content": PRICING})
    created = client.post(f"{API}/projects/{pid}/files", json={"path": "shop/cart.py", "content": "x = 1\n"})
    fid = created.json()["file"]["id"]
    # 3. Open file.
    assert client.get(f"{API}/projects/{pid}/files/{fid}").json()["content"] == "x = 1\n"
    # 4-5. Edit code and receive diagnostics (live analysis, then the saved analysis).
    live = client.post(
        f"{API}/analysis/code", json={"code": CART, "language": "python", "file_path": "shop/cart.py"}
    )
    undefined = [d for d in live.json()["diagnostics"] if "total" in d["message"]]
    assert undefined
    saved = client.patch(f"{API}/projects/{pid}/files/{fid}", json={"content": CART}).json()
    assert saved["analysis"]["diagnostic_count"] >= 1
    # 6. Search project.
    found = client.post(f"{API}/projects/{pid}/search", json={"query": "cart_total"}).json()
    assert found["results"][0]["file_path"] == "shop/cart.py"
    # 7-8. Ask AI about the error and receive an explanation (stub model).
    stub.answers.append(explanation())
    diagnostic = {
        "id": "d1",
        "severity": "error",
        "message": undefined[0]["message"],
        "source": undefined[0]["source"],
        "code": undefined[0].get("code"),
        "category": undefined[0]["category"],
        "line": undefined[0]["line"],
        "column": undefined[0]["column"],
        "end_line": undefined[0]["end_line"],
        "end_column": undefined[0]["end_column"],
    }
    explain = client.post(
        f"{API}/ai/explain",
        json={
            "code": CART,
            "language": "python",
            "file_path": "shop/cart.py",
            "project_id": pid,
            "diagnostic": diagnostic,
            "diagnostics": [diagnostic],
        },
    )
    assert explain.status_code == 200, explain.text
    assert explain.json()["cause"] == "The accumulator is never initialised."
    # 9-11. Request a fix, review the proposal, reject it: the file is unchanged.
    stub.answers.extend(proposal("    total = 0\n    for item in items:"))
    run = client.post(f"{API}/agent/run", json={"project_id": pid, "message": "Fix the error"}).json()
    first = run["actions"][0]
    assert first["status"] == "pending"
    assert "+    total = 0" in first["diff"]
    assert client.get(f"{API}/projects/{pid}/files/{fid}").json()["content"] == CART  # not applied yet
    rejected = client.post(f"{API}/agent/actions/{first['id']}/reject").json()
    assert rejected["action"]["status"] == "rejected"
    assert client.get(f"{API}/projects/{pid}/files/{fid}").json()["content"] == CART
    # 12-14. Request another proposal, approve it, and the file changes.
    stub.answers.extend(proposal("    total = 0.0\n    for item in items:"))
    second = client.post(f"{API}/agent/run", json={"project_id": pid, "message": "Try again"}).json()[
        "actions"
    ][0]
    approved = client.post(f"{API}/agent/actions/{second['id']}/approve")
    assert approved.status_code == 200, approved.text
    content = client.get(f"{API}/projects/{pid}/files/{fid}").json()["content"]
    assert content.startswith("def cart_total(items):\n    total = 0.0\n    for item in items:")
    # 15. Re-run diagnostics: the undefined name is gone.
    assert not [d for d in approved.json()["diagnostics"] if "total" in d["message"]]
    rerun = client.post(f"{API}/projects/{pid}/files/{fid}/analyses")
    assert rerun.status_code == 201
    assert not [d for d in rerun.json()["diagnostics"] if "Undefined name" in d["message"]]
    # The rejected proposal can no longer be approved, and the applied one not twice.
    assert client.post(f"{API}/agent/actions/{first['id']}/approve").status_code == 409
    assert client.post(f"{API}/agent/actions/{second['id']}/approve").status_code == 409


def test_workflow_c_security_between_users(
    database_url: str, workspace: Path, client_factory: Callable[[FastAPI], TestClient]
) -> None:
    app, stub = stub_app(database_url, workspace)
    alice, bob = client_factory(app), client_factory(app)
    register(alice)
    register(bob, email="bob@example.com", name="Bob")
    # 1. User A creates a project (indexed for semantic retrieval) with a pending proposal.
    pid = alice.post(f"{API}/projects", json={"name": "Private"}).json()["id"]
    fid = alice.post(f"{API}/projects/{pid}/files", json={"path": "shop/cart.py", "content": CART}).json()[
        "file"
    ]["id"]
    assert alice.post(f"{API}/projects/{pid}/rag/index").status_code == 200
    stub.answers.extend(proposal("    total = 0\n    for item in items:"))
    action = alice.post(f"{API}/agent/run", json={"project_id": pid, "message": "fix"}).json()["actions"][0][
        "id"
    ]

    # 2-3. User B cannot see it.
    assert pid not in json.dumps(bob.get(f"{API}/projects").json())
    assert bob.get(f"{API}/projects/{pid}").status_code == 404
    assert bob.get(f"{API}/projects/{pid}/files").status_code == 404
    assert bob.get(f"{API}/projects/{pid}/files/{fid}").status_code == 404
    # 4. User B cannot search it, in any mode.
    for mode in ("deterministic", "semantic", "hybrid"):
        response = bob.post(f"{API}/projects/{pid}/search", json={"query": "cart_total", "mode": mode})
        assert response.status_code == 404, mode
    # 5. User B cannot retrieve semantic context, index status, or run the agent on it.
    assert bob.post(f"{API}/projects/{pid}/context", json={"current_file": "shop/cart.py"}).status_code == 404
    assert bob.get(f"{API}/projects/{pid}/rag/index").status_code == 404
    assert bob.post(f"{API}/projects/{pid}/rag/index").status_code == 404
    assert bob.post(f"{API}/agent/run", json={"project_id": pid, "message": "x"}).status_code == 404
    # 6. User B cannot modify it.
    assert bob.patch(f"{API}/projects/{pid}/files/{fid}", json={"content": "x = 1\n"}).status_code == 404
    assert bob.delete(f"{API}/projects/{pid}/files/{fid}").status_code == 404
    assert bob.delete(f"{API}/projects/{pid}").status_code == 404
    # 7. User B cannot approve or reject its proposals.
    assert bob.post(f"{API}/agent/actions/{action}/approve").status_code == 404
    assert bob.post(f"{API}/agent/actions/{action}/reject").status_code == 404
    # Nothing changed for user A; B's own semantic search sees none of A's code.
    assert alice.get(f"{API}/projects/{pid}/files/{fid}").json()["content"] == CART
    bob_project = bob.post(f"{API}/projects", json={"name": "Bob's"}).json()["id"]
    bob.post(
        f"{API}/projects/{bob_project}/files", json={"path": "b.py", "content": "def b():\n    return 1\n"}
    )
    bob.post(f"{API}/projects/{bob_project}/rag/index")
    results = bob.post(
        f"{API}/projects/{bob_project}/search", json={"query": "cart total items price", "mode": "semantic"}
    ).json()["results"]
    assert all(r["file_path"] == "b.py" for r in results)
