"""Module 22: the documented configuration matches what the backend reads (repository-level checks).

npm run test:infra
"""

from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))  # the backend package, as in backend/tests

from app.core.config import Settings  # noqa: E402

# Set by the hosting platform, or internal.
UNDOCUMENTED = {
    "CODEWALK_APP_NAME",
    "VERCEL",
    "VERCEL_URL",
    "VERCEL_BRANCH_URL",
    "VERCEL_PROJECT_PRODUCTION_URL",
}


def _env_names() -> set[str]:
    return {
        field.validation_alias.upper()
        if isinstance(field.validation_alias, str)
        else f"CODEWALK_{name.upper()}"
        for name, field in Settings.model_fields.items()
    }


def test_every_setting_is_documented_in_the_example_environment() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))
    assert _env_names() - documented - UNDOCUMENTED == set()


def test_production_example_documents_only_known_names() -> None:
    """Every variable in .env.production.example is a setting the backend reads or a Compose input."""
    known = {
        (
            field.validation_alias.upper()
            if isinstance(field.validation_alias, str)
            else f"CODEWALK_{name.upper()}"
        )
        for name, field in Settings.model_fields.items()
    }
    compose = set(
        re.findall(r"\$\{([A-Z0-9_]+)", (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    )
    example = set(
        re.findall(
            r"^([A-Z][A-Z0-9_]+)=", (REPO_ROOT / ".env.production.example").read_text(encoding="utf-8"), re.M
        )
    )
    assert example - known - compose == set()


def test_token_key_generation_command_in_the_docs_makes_a_valid_key() -> None:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()  # the documented one-liner
    assert Settings(_env_file=None, token_encryption_key=key).token_encryption_key is not None  # type: ignore[call-arg]
    docs = Path(REPO_ROOT / "docs" / "deployment" / "production.md").read_text(encoding="utf-8")
    assert "base64.urlsafe_b64encode(os.urandom(32))" in docs
