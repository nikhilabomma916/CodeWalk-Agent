"""Typed application settings.

All runtime configuration comes from environment variables (prefixed with
``CODEWALK_``) or from ``.env`` files. Secrets are stored as ``SecretStr`` so
they never appear in ``repr()`` output, logs, or API responses.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

# Later files override earlier ones: the repository-level .env is shared with
# the frontend, backend/.env can hold backend-only overrides.
ENV_FILES = (REPO_ROOT / ".env", BACKEND_DIR / ".env")

INSECURE_SECRET_KEYS = frozenset({"", "change-me", "changeme", "secret", "dev-secret-key"})
MIN_PRODUCTION_SECRET_KEY_LENGTH = 32


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CODEWALK_",
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "CodeWalk Agent API"
    env: Environment = Environment.DEVELOPMENT

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    api_v1_prefix: str = "/api/v1"

    # Comma-separated in the environment, e.g. "http://localhost:3000,http://127.0.0.1:3000".
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # When None, docs are enabled everywhere except production.
    docs_enabled: bool | None = None

    # PostgreSQL, e.g. postgresql+psycopg://user:password@localhost:5432/codewalk.
    # When unset, the API still serves analysis; persistence endpoints return 503.
    database_url: SecretStr | None = None
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    # Reserved for the AI modules; not used yet.
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None
    ai_request_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    secret_key: SecretStr = SecretStr("")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"

    # Must exceed max_source_bytes: JSON encoding can expand source text.
    max_request_body_bytes: int = Field(default=6 * 1024 * 1024, gt=0)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)

    # Largest single source file accepted for analysis or storage.
    max_source_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    # Per-analyzer time limit (Ruff, TypeScript worker).
    analysis_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    # Node.js binary for the TypeScript analyzer; found on PATH when unset.
    node_binary: str | None = None
    # Code analyses kept per file (older ones are pruned).
    analysis_history_per_file: int = Field(default=20, ge=1, le=1000)

    # Server directory whose sub-folders may be linked to projects and scanned.
    # Scanning is disabled when unset. Paths outside it are never read.
    workspace_root: Path | None = None
    scan_max_files: int = Field(default=10_000, ge=1, le=100_000)

    health_check_timeout_seconds: float = Field(default=3.0, gt=0, le=60)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        cleaned: list[str] = []
        for origin in origins:
            if origin == "*":
                raise ValueError("Wildcard CORS origin is not allowed; list explicit origins instead")
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"CORS origin must start with http:// or https://: {origin!r}")
            cleaned.append(origin.rstrip("/"))
        return cleaned

    @field_validator("api_v1_prefix")
    @classmethod
    def _validate_prefix(cls, prefix: str) -> str:
        if not prefix.startswith("/") or prefix.endswith("/"):
            raise ValueError("API prefix must start with '/' and must not end with '/'")
        return prefix

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("ai_provider", "ai_model", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("workspace_root", mode="before")
    @classmethod
    def _blank_path_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("workspace_root")
    @classmethod
    def _validate_workspace_root(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        if not value.is_absolute():
            raise ValueError("CODEWALK_WORKSPACE_ROOT must be an absolute path")
        if not value.is_dir():
            raise ValueError("CODEWALK_WORKSPACE_ROOT must be an existing directory")
        return value.resolve()

    @field_validator("node_binary", mode="before")
    @classmethod
    def _blank_node_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", "ai_api_key", mode="before")
    @classmethod
    def _blank_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_limits(self) -> Settings:
        if self.max_request_body_bytes <= self.max_source_bytes:
            raise ValueError("CODEWALK_MAX_REQUEST_BODY_BYTES must be larger than CODEWALK_MAX_SOURCE_BYTES")
        return self

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.env is Environment.PRODUCTION:
            key = self.secret_key.get_secret_value()
            if key.lower() in INSECURE_SECRET_KEYS or len(key) < MIN_PRODUCTION_SECRET_KEY_LENGTH:
                raise ValueError(
                    "CODEWALK_SECRET_KEY must be set to a random value of at least "
                    f"{MIN_PRODUCTION_SECRET_KEY_LENGTH} characters in production"
                )
            if not self.cors_origins:
                raise ValueError("CODEWALK_CORS_ORIGINS must list the frontend origin(s)")
        return self

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def docs_are_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Settings loaded from the process environment (cached for the process lifetime)."""
    return Settings()
