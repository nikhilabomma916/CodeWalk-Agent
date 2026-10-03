"""Semantic retrieval status and indexing (Module 10)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievalStatusResponse(BaseModel):
    """Configuration state only: computing it never calls the provider. No credential is included."""

    enabled: bool
    configured: bool
    available: bool
    provider: str | None
    model: str | None
    dimensions: int
    detail: str | None


class IndexStatusResponse(BaseModel):
    available: bool = Field(description="Whether semantic retrieval can be used on this server.")
    model: str | None
    indexable_files: int = Field(description="Searchable files with stored, non-blank content.")
    indexed_files: int = Field(description="Files whose embeddings match their current content.")
    stale_files: int = Field(description="Files that are new or changed since they were indexed.")
    chunks: int = Field(description="Current embedded chunks.")


class IndexRunResponse(BaseModel):
    files_indexed: int
    chunks_embedded: int = Field(description="Chunks sent to the embedding provider in this run.")
    chunks_reused: int = Field(description="Unchanged chunks whose stored vectors were kept.")
    tokens_used: int = Field(description="Tokens reported by the embedding provider.")
    remaining_files: int = Field(description="Files still to index (run again to continue).")
    status: IndexStatusResponse
