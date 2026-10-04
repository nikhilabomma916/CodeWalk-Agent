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
        # A failed validation must not print the raw input: it holds the database URL and keys.
        hide_input_in_errors=True,
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

    # AI assistance (analysis, explanations, fix suggestions). Off unless enabled AND a provider
    # credential is present; deterministic analysis never depends on it.
    ai_enabled: bool = False
    ai_provider: str | None = None  # "anthropic" (default when unset)
    ai_model: str | None = None  # provider default when unset
    # Provider credential. CODEWALK_AI_API_KEY wins; otherwise ANTHROPIC_API_KEY is used.
    ai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    ai_timeout_seconds: float = Field(default=90.0, gt=0, le=600)
    ai_max_tokens: int = Field(default=16_000, ge=256, le=64_000)
    # Reasoning effort sent to providers that support it.
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    # AI requests allowed per user within the window (then HTTP 429).
    ai_max_requests: int = Field(default=30, ge=1, le=10_000)
    ai_window_seconds: int = Field(default=600, ge=1, le=86_400)

    # Semantic retrieval (Module 10): code embeddings in PostgreSQL (pgvector). Off unless enabled
    # AND an embedding credential is present; deterministic search never depends on it.
    # Read from the unprefixed RAG_ENABLED, RAG_EMBEDDING_PROVIDER, RAG_EMBEDDING_MODEL, VOYAGE_API_KEY;
    # the tuning settings below use the usual CODEWALK_ prefix.
    rag_enabled: bool = Field(default=False, validation_alias="rag_enabled")
    rag_embedding_provider: str | None = Field(  # "voyage" (default when unset)
        default=None,
        validation_alias="rag_embedding_provider",
    )
    rag_embedding_model: str | None = Field(  # provider default when unset
        default=None, validation_alias="rag_embedding_model"
    )
    voyage_api_key: SecretStr | None = Field(default=None, validation_alias="voyage_api_key")
    rag_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    # Query embeddings (semantic/hybrid searches, AI context) allowed per user within the window;
    # past it, searches fall back to deterministic results with a warning.
    rag_max_queries: int = Field(default=120, ge=1, le=100_000)
    # Indexing runs allowed per user within the window (then HTTP 429).
    rag_max_index_runs: int = Field(default=10, ge=1, le=10_000)
    rag_window_seconds: int = Field(default=600, ge=1, le=86_400)
    # Chunks embedded by one indexing run; a larger project is indexed over several runs.
    rag_max_chunks_per_run: int = Field(default=2000, ge=1, le=50_000)

    # Project-aware agent (Module 11): bounded tool loop over the AI provider. Needs AI assistance.
    agent_max_steps: int = Field(default=8, ge=2, le=20)  # model turns per run (each: one tool or answer)
    agent_timeout_seconds: float = Field(default=240.0, gt=0, le=1800)  # whole run, all steps
    agent_max_context_chars: int = Field(default=60_000, ge=10_000, le=400_000)  # tool results kept
    agent_max_actions: int = Field(default=3, ge=1, le=10)  # proposed changes per run
    # Agent runs allowed per user within the window (then HTTP 429).
    agent_max_runs: int = Field(default=20, ge=1, le=10_000)
    agent_window_seconds: int = Field(default=600, ge=1, le=86_400)

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

    # File versions kept per project file (older ones are pruned).
    file_version_history_limit: int = Field(default=50, ge=1, le=1000)

    # Login sessions: an opaque random token in an httpOnly cookie; only its hash is stored.
    session_cookie_name: str = Field(default="codewalk_session", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    session_ttl_hours: int = Field(default=168, ge=1, le=24 * 90)
    # Send the cookie over HTTPS only. Defaults to on in production, off otherwise.
    session_cookie_secure: bool | None = None
    # Failed logins allowed per client address and email within the window (then HTTP 429).
    login_max_attempts: int = Field(default=10, ge=1, le=1000)
    login_window_seconds: int = Field(default=900, ge=1, le=86_400)
    # Registrations allowed per client address within the window (then HTTP 429).
    register_max_attempts: int = Field(default=20, ge=1, le=10_000)
    register_window_seconds: int = Field(default=3600, ge=1, le=86_400)

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

    @field_validator(
        "ai_provider", "ai_model", "rag_embedding_provider", "rag_embedding_model", mode="before"
    )
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

    @field_validator("database_url", "ai_api_key", "anthropic_api_key", "voyage_api_key", mode="before")
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
            # An empty list is the same-origin deployment behind the reverse proxy (frontend and API
            # on one origin): no cross-origin access at all, and the origin check still accepts the
            # API's own origin. Development defaults must not carry over: any listed origin is an
            # explicit HTTPS origin, and the session cookie is never sent over plain HTTP.
            insecure = [origin for origin in self.cors_origins if not origin.startswith("https://")]
            if insecure:
                raise ValueError(
                    "CODEWALK_CORS_ORIGINS must use https:// in production (got " + ", ".join(insecure) + ")"
                )
            if self.session_cookie_secure is False:
                raise ValueError("CODEWALK_SESSION_COOKIE_SECURE cannot be false in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def ai_credential(self) -> SecretStr | None:
        return self.ai_api_key or self.anthropic_api_key

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_production

    @property
    def docs_are_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Settings loaded from the process environment (cached for the process lifetime)."""
    return Settings()
