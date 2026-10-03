"""Regression (Module 14): credential files must never be stored, searched, indexed, or given to the AI.

Found during Module 14 path-security testing: the secret-file rule looked only at the
file *name*, so well-known credential locations identified by their folder
(``.aws/credentials``, ``.docker/config.json``, ``.kube/config``, ``.ssh/config``) and
common secret file names (``credentials.json``, ``secrets.yaml``, ``*.tfstate``,
``.pgpass``) could be stored, appeared in search, and could reach the AI and
embedding providers as project context. All values below are obviously fake.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.files import FileRepository
from app.services.file_content import file_values

FAKE_KEY = "AKIAFAKEFAKEFAKEFAKE"
SECRET_PATHS = [
    ".aws/credentials",
    ".aws/config",
    "deploy/.docker/config.json",
    ".kube/config",
    ".ssh/config",
    ".gnupg/secring.gpg",
    "credentials.json",
    "config/client_secret_123.json",
    "service-account-prod.json",
    "secrets.yaml",
    "helm/secrets.yml",
    "infra/terraform.tfstate",
    ".pgpass",
    ".htpasswd",
]


@pytest.mark.parametrize("path", SECRET_PATHS)
def test_credential_paths_are_not_stored(api: TestClient, path: str) -> None:
    project = api.post("/api/v1/projects", json={"name": "Secrets"}).json()
    response = api.post(
        f"/api/v1/projects/{project['id']}/files", json={"path": path, "content": f"key = {FAKE_KEY}\n"}
    )
    assert response.status_code == 422, (path, response.text)
    assert FAKE_KEY not in response.text


def test_legacy_credential_rows_stay_invisible(api: TestClient, session: Session) -> None:
    """Rows stored before this rule existed are never searched, given as context, or read by tools."""
    project: dict[str, Any] = api.post("/api/v1/projects", json={"name": "Legacy"}).json()

    pid = uuid.UUID(project["id"])
    for path in (".aws/credentials", "secrets.yaml"):
        FileRepository(session).create(
            project_id=pid, **file_values(path, f"aws_secret_access_key = {FAKE_KEY}\n")
        )
    session.commit()
    api.post(f"/api/v1/projects/{pid}/files", json={"path": "app.py", "content": "import boto3\n"})

    found = api.post(f"/api/v1/projects/{pid}/search", json={"query": FAKE_KEY}).json()
    assert found["results"] == []
    assert found["indexed_files"] == 1
    context = api.post(f"/api/v1/projects/{pid}/context", json={"current_file": "app.py", "query": "aws"})
    assert FAKE_KEY not in context.text
    snippet = api.post(f"/api/v1/projects/{pid}/snippet", json={"file_path": "secrets.yaml", "line": 1})
    assert snippet.status_code in (404, 422)
    assert FAKE_KEY not in snippet.text
