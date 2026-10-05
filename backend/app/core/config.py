"""Typed application settings.

All runtime configuration comes from environment variables (prefixed with
``CODEWALK_``) or from ``.env`` files. Secrets are stored as ``SecretStr`` so
they never appear in ``repr()`` output, logs, or API responses.
"""

from __future__ import annotations

import base64
import binascii
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

# Later files override earlier ones: the repository-level .env is shared with
# the frontend, backend/.env can hold backend-only overrides.
ENV_FILES = (REPO_ROOT / ".env", BACKEND_DIR / ".env")

# A bare host name as Vercel provides it in VERCEL_URL and friends, e.g. "codewalk-abc123.vercel.app".
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST_NAME = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})+$")

# Vercel Functions refuse request bodies over 4.5 MB (413 FUNCTION_PAYLOAD_TOO_LARGE, not this API's
# JSON error) before the application sees them. On Vercel the API's own limit is capped at that.
VERCEL_MAX_REQUEST_BODY_BYTES = 4_500_000

AI_PROVIDERS = ("anthropic", "openai", "gemini", "openrouter", "ollama")
# Model ids as providers spell them: "gpt-5", "gemini-2.5-pro", "vendor/model", "llama3.1:8b".
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


# GitHub OAuth scopes CodeWalk may request: read the account, and read repositories. "repo" is the only
# scope GitHub offers for private repositories (it also grants write access CodeWalk never uses).
GITHUB_ALLOWED_SCOPES = frozenset({"repo", "public_repo", "read:user", "read:org"})


def decode_encryption_key(value: str) -> bytes | None:
    """32 key bytes from base64 (url-safe or standard, padding optional); None when it is not one."""
    text = value.strip()
    try:
        key = base64.urlsafe_b64decode(text.replace("+", "-").replace("/", "_") + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error):
        return None
    return key if len(key) == 32 else None


def _credential_free_url(value: str, *, schemes: tuple[str, ...]) -> bool:
    """An absolute URL with one of ``schemes``, a host, and no user:password part."""
    parsed = urlsplit(value)
    return parsed.scheme in schemes and bool(parsed.hostname) and parsed.username is None


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
    # GET /metrics (Prometheus text format; outside /api, so the reverse proxy does not route it).
    metrics_enabled: bool = True

    # PostgreSQL, e.g. postgresql+psycopg://user:password@localhost:5432/codewalk.
    # When unset, the API still serves analysis; persistence endpoints return 503.
    database_url: SecretStr | None = None
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    # psycopg prepares statements that run often. Connection poolers in transaction mode (for
    # example Supabase's pooler on port 6543, or PgBouncer without prepared-statement support)
    # move connections between clients, and prepared statements then fail. Set false for them.
    database_prepared_statements: bool = True
    # Longest a single SQL statement may run before PostgreSQL cancels it (the request then fails
    # with a 503 instead of holding a pooled connection indefinitely). Migrations are not affected.
    database_statement_timeout_seconds: float = Field(default=30.0, ge=1, le=3600)

    # AI assistance (analysis, explanations, fix suggestions). Off unless enabled AND a provider
    # credential is present; deterministic analysis never depends on it.
    ai_enabled: bool = False
    # One provider, chosen explicitly: anthropic (default when unset), openai, gemini, openrouter or
    # ollama. There is no fallback to another provider when the chosen one fails.
    ai_provider: str | None = None
    ai_model: str | None = None  # provider default when unset (only Anthropic has one)
    # Provider credential. CODEWALK_AI_API_KEY wins; otherwise the selected provider's own variable
    # (ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY). Never another provider's.
    ai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    # Module 17: CODEWALK_AI_PROVIDER=openai talks to an OpenAI-compatible API.
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    ai_base_url: str | None = None  # OpenAI-compatible server; https only (http for localhost)
    # Module 19: Gemini (Google's OpenAI-compatible endpoint), OpenRouter, and a self-hosted Ollama.
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    openrouter_api_key: SecretStr | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_model: str | None = Field(default=None, validation_alias="OPENROUTER_MODEL")
    openrouter_base_url: str | None = Field(default=None, validation_alias="OPENROUTER_BASE_URL")
    ollama_base_url: str | None = Field(default=None, validation_alias="OLLAMA_BASE_URL")
    ollama_model: str | None = Field(default=None, validation_alias="OLLAMA_MODEL")
    # Optional comma-separated allowlist: when set, the configured model must be one of these.
    ai_allowed_models: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ai_timeout_seconds: float = Field(default=90.0, gt=0, le=600)
    ai_max_tokens: int = Field(default=16_000, ge=256, le=64_000)
    # Largest prompt (system + user text) sent to a provider; larger requests fail before any call.
    ai_max_input_chars: int = Field(default=400_000, ge=10_000, le=4_000_000)
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
    agent_max_tool_calls: int = Field(default=12, ge=1, le=50)  # tool calls per run (all kinds)
    # Provider tokens (input + output) one run may use before it stops and answers.
    agent_max_tokens_per_run: int = Field(default=400_000, ge=10_000, le=5_000_000)
    # Agent runs allowed per user within the window (then HTTP 429).
    agent_max_runs: int = Field(default=20, ge=1, le=10_000)
    agent_window_seconds: int = Field(default=600, ge=1, le=86_400)

    secret_key: SecretStr = SecretStr("")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"

    # Must exceed max_source_bytes: JSON encoding can expand source text. On Vercel the effective
    # limit is at most VERCEL_MAX_REQUEST_BODY_BYTES (see request_body_limit).
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
    # Per account, from any address (credential stuffing spread over many addresses). Higher
    # than the per-address limit so an attacker cannot cheaply lock a real user out.
    login_account_max_attempts: int = Field(default=50, ge=1, le=10_000)
    # Registrations allowed per client address within the window (then HTTP 429).
    register_max_attempts: int = Field(default=20, ge=1, le=10_000)
    register_window_seconds: int = Field(default=3600, ge=1, le=86_400)

    # Server directory whose sub-folders may be linked to projects and scanned.
    # Scanning is disabled when unset. Paths outside it are never read.
    workspace_root: Path | None = None
    scan_max_files: int = Field(default=10_000, ge=1, le=100_000)

    health_check_timeout_seconds: float = Field(default=3.0, gt=0, le=60)

    # GitHub (Module 20): connect an account with OAuth and import repositories as projects. Off
    # unless the OAuth app's client id, secret and callback URL and the token encryption key are set.
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None
    # Must match the OAuth app's "Authorization callback URL": <API origin>/api/v1/github/callback.
    github_callback_url: str | None = None
    # OAuth scopes. Empty (default): public repositories only. "repo" also allows private ones, but
    # GitHub grants read AND write access with it; CodeWalk itself only reads.
    github_scopes: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Where the browser returns after connecting (the frontend). Unset: the first allowed origin,
    # or the API's own origin when the frontend is served from the same origin.
    app_url: str | None = None
    # AES-256-GCM key for GitHub tokens at rest: 32 random bytes, base64 (url-safe or standard).
    token_encryption_key: SecretStr | None = None
    # Previous keys, comma-separated, still accepted for decryption during a key rotation.
    token_encryption_old_keys: SecretStr | None = None
    github_max_archive_bytes: int = Field(default=50 * 1024 * 1024, ge=1024 * 1024, le=1024 * 1024 * 1024)
    github_max_repository_bytes: int = Field(
        default=100 * 1024 * 1024, ge=1024 * 1024, le=2 * 1024 * 1024 * 1024
    )
    github_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    github_import_max_runs: int = Field(default=10, ge=1, le=1000)
    github_import_window_seconds: int = Field(default=3600, ge=1, le=86_400)
    # On SIGTERM, in-flight requests get this long to finish before they are cancelled and the
    # shutdown cleanup (TypeScript worker, database pool) runs. Keep it below the host's grace
    # period: 30 s on Vercel and in docker-compose.prod.yml (the container is killed after that).
    shutdown_timeout_seconds: int = Field(default=20, ge=1, le=600)

    # Vercel (read only when VERCEL=1, which Vercel sets in its build and runtime environments).
    # The deployment's own URLs are allowed origins, so a preview or production deployment accepts
    # requests from its own pages without listing each generated URL in CODEWALK_CORS_ORIGINS.
    # All are bare host names (no scheme); the origin is always https://<host>.
    vercel: str | None = Field(default=None, validation_alias="vercel")
    vercel_url: str | None = Field(default=None, validation_alias="vercel_url")
    vercel_branch_url: str | None = Field(default=None, validation_alias="vercel_branch_url")
    vercel_project_production_url: str | None = Field(
        default=None, validation_alias="vercel_project_production_url"
    )

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

    @field_validator(
        "vercel", "vercel_url", "vercel_branch_url", "vercel_project_production_url", mode="before"
    )
    @classmethod
    def _blank_platform_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("vercel_url", "vercel_branch_url", "vercel_project_production_url")
    @classmethod
    def _validate_host_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        host = value.strip().lower()
        if not _HOST_NAME.match(host):
            raise ValueError("VERCEL_*_URL values must be host names such as app.vercel.app")
        return host

    @field_validator("node_binary", mode="before")
    @classmethod
    def _blank_node_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "openrouter_model", "ollama_model", "openrouter_base_url", "ollama_base_url", mode="before"
    )
    @classmethod
    def _blank_provider_setting_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("ai_allowed_models", mode="before")
    @classmethod
    def _parse_allowed_models(cls, value: object) -> object:
        if isinstance(value, str):
            return [model.strip() for model in value.split(",") if model.strip()]
        return value

    @field_validator("ai_model", "openrouter_model", "ollama_model", "ai_allowed_models")
    @classmethod
    def _validate_model_names(cls, value: str | list[str] | None) -> str | list[str] | None:
        for name in [value] if isinstance(value, str) else value or []:
            if not _MODEL_NAME.match(name):
                raise ValueError("AI model names may contain only letters, digits and . _ : / @ + -")
        return value

    @field_validator("openrouter_base_url")
    @classmethod
    def _secure_openrouter_url(cls, value: str | None) -> str | None:
        if value is not None and not _credential_free_url(value, schemes=("https",)):
            raise ValueError("OPENROUTER_BASE_URL must be an https:// URL without credentials")
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def _valid_ollama_url(cls, value: str | None) -> str | None:
        if value is not None and not _credential_free_url(value, schemes=("http", "https")):
            raise ValueError("OLLAMA_BASE_URL must be an http(s):// URL without credentials")
        return value

    @field_validator("github_client_id", "github_callback_url", "app_url", mode="before")
    @classmethod
    def _blank_github_setting_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("github_client_id")
    @classmethod
    def _validate_github_client_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value):
            raise ValueError("CODEWALK_GITHUB_CLIENT_ID has an unexpected format")
        return value

    @field_validator("github_callback_url", "app_url")
    @classmethod
    def _validate_github_urls(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _credential_free_url(value, schemes=("http", "https")) or urlsplit(value).query:
            raise ValueError("CODEWALK_GITHUB_CALLBACK_URL and CODEWALK_APP_URL must be plain http(s) URLs")
        return value.rstrip("/")

    @field_validator("github_scopes", mode="before")
    @classmethod
    def _parse_github_scopes(cls, value: object) -> object:
        if isinstance(value, str):
            return [scope for scope in re.split(r"[\s,]+", value) if scope]
        return value

    @field_validator("github_scopes")
    @classmethod
    def _validate_github_scopes(cls, value: list[str]) -> list[str]:
        # Reading repositories never needs more; write or admin scopes are refused outright.
        unknown = [scope for scope in value if scope not in GITHUB_ALLOWED_SCOPES]
        if unknown:
            raise ValueError(
                "CODEWALK_GITHUB_SCOPES may contain only: " + ", ".join(sorted(GITHUB_ALLOWED_SCOPES))
            )
        return sorted(set(value))

    @field_validator(
        "token_encryption_key", "token_encryption_old_keys", "github_client_secret", mode="before"
    )
    @classmethod
    def _blank_token_key_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("token_encryption_key")
    @classmethod
    def _validate_token_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and decode_encryption_key(value.get_secret_value()) is None:
            raise ValueError("CODEWALK_TOKEN_ENCRYPTION_KEY must be 32 random bytes, base64-encoded")
        return value

    @field_validator("token_encryption_old_keys")
    @classmethod
    def _validate_old_token_keys(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and any(
            decode_encryption_key(key) is None for key in value.get_secret_value().split(",") if key.strip()
        ):
            raise ValueError("CODEWALK_TOKEN_ENCRYPTION_OLD_KEYS must hold base64-encoded 32-byte keys")
        return value

    @field_validator("ai_base_url")
    @classmethod
    def _secure_base_url(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        value = value.strip()
        local = value.startswith(("http://localhost", "http://127.0.0.1"))
        if not value.startswith("https://") and not local:
            raise ValueError("CODEWALK_AI_BASE_URL must use https:// (http:// only for localhost)")
        return value

    @field_validator(
        "database_url",
        "ai_api_key",
        "anthropic_api_key",
        "openai_api_key",
        "gemini_api_key",
        "openrouter_api_key",
        "voyage_api_key",
        mode="before",
    )
    @classmethod
    def _blank_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_limits(self) -> Settings:
        if self.request_body_limit <= self.max_source_bytes:
            message = "CODEWALK_MAX_REQUEST_BODY_BYTES must be larger than CODEWALK_MAX_SOURCE_BYTES"
            if self.on_vercel:
                message += f" (on Vercel it is at most {VERCEL_MAX_REQUEST_BODY_BYTES} bytes)"
            raise ValueError(message)
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
            for name, url in (
                ("CODEWALK_GITHUB_CALLBACK_URL", self.github_callback_url),
                ("CODEWALK_APP_URL", self.app_url),
            ):
                if url is not None and not url.startswith("https://"):
                    raise ValueError(f"{name} must use https:// in production")
            # Prompts carry project source code: in production they never cross a network in plain
            # HTTP. A local Ollama on the same host (loopback) is the one exception.
            ollama = urlsplit(self.ollama_base_url) if self.ollama_base_url else None
            if ollama and ollama.scheme != "https" and ollama.hostname not in _LOOPBACK_HOSTS:
                raise ValueError(
                    "OLLAMA_BASE_URL must use https:// in production (http:// only for localhost)"
                )
        return self

    @model_validator(mode="after")
    def _validate_ai_model(self) -> Settings:
        if self.ai_enabled and self.ai_allowed_models:
            model = self.ai_selected_model
            if model is not None and model not in self.ai_allowed_models:
                raise ValueError("The configured AI model is not in CODEWALK_AI_ALLOWED_MODELS")
        return self

    @property
    def ai_provider_name(self) -> str:
        return (self.ai_provider or "anthropic").strip().lower()

    @property
    def ai_selected_model(self) -> str | None:
        """The model for the selected provider: OPENROUTER_MODEL/OLLAMA_MODEL win over CODEWALK_AI_MODEL."""
        provider_model = {"openrouter": self.openrouter_model, "ollama": self.ollama_model}.get(
            self.ai_provider_name
        )
        return provider_model or self.ai_model

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def on_vercel(self) -> bool:
        return self.vercel == "1"

    @property
    def request_body_limit(self) -> int:
        """CODEWALK_MAX_REQUEST_BODY_BYTES, capped on Vercel at the platform's request body limit."""
        if self.on_vercel:
            return min(self.max_request_body_bytes, VERCEL_MAX_REQUEST_BODY_BYTES)
        return self.max_request_body_bytes

    @property
    def allowed_origins(self) -> list[str]:
        """CODEWALK_CORS_ORIGINS plus, on Vercel, the deployment's own https:// URLs."""
        origins = list(self.cors_origins)
        if self.on_vercel:
            for host in (self.vercel_url, self.vercel_branch_url, self.vercel_project_production_url):
                if host and f"https://{host}" not in origins:
                    origins.append(f"https://{host}")
        return origins

    @property
    def ai_credential(self) -> SecretStr | None:
        """CODEWALK_AI_API_KEY, else the selected provider's own variable (never another provider's key)."""
        if self.ai_api_key:
            return self.ai_api_key
        own = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "openrouter": self.openrouter_api_key,
        }
        return own.get(self.ai_provider_name)  # Ollama needs none (CODEWALK_AI_API_KEY if behind a proxy)

    @property
    def github_configured(self) -> bool:
        return bool(
            self.github_client_id
            and self.github_client_secret
            and self.github_callback_url
            and self.token_encryption_key
        )

    @property
    def post_oauth_url(self) -> str:
        """The frontend's base URL for redirects after GitHub's callback (empty: same origin)."""
        if self.app_url:
            return self.app_url
        return self.cors_origins[0] if self.cors_origins else ""

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
