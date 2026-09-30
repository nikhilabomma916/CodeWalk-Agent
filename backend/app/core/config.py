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

    # Consumed by the persistence module (Module 8). Not connected yet.
    database_url: SecretStr | None = None

    # Consumed by the AI module (Module 9). Not connected yet.
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None
    ai_request_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    secret_key: SecretStr = SecretStr("")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"

    max_request_body_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)

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

    @field_validator("database_url", "ai_api_key", mode="before")
    @classmethod
    def _blank_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

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
