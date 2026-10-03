"""Project search and context.

Module 9 search is deterministic. Module 10 adds optional semantic retrieval (embeddings) and a
hybrid mode that fuses both result lists by rank; deterministic stays the default.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ai import DiagnosticInput
from app.schemas.common import ProjectFilePath, RelativePath
from app.services.languages import Language
from app.services.project_intelligence.models import SymbolKind

MAX_RESULTS = 100


class MatchType(StrEnum):
    SYMBOL_EXACT = "symbol_exact"
    FILE_NAME = "file_name"
    SYMBOL_PREFIX = "symbol_prefix"
    SYMBOL_TOKENS = "symbol_tokens"
    FILE_PATH = "file_path"
    IMPORT = "import"
    IDENTIFIER = "identifier"
    TEXT = "text"
    SEMANTIC = "semantic"  # Module 10: found by embedding similarity


class SearchMode(StrEnum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    symbol_type: SymbolKind | None = Field(default=None, description="Only symbols of this kind.")
    path_prefix: RelativePath | None = Field(default=None, description="Only files under this folder.")
    match_types: list[MatchType] | None = Field(default=None, description="Only these kinds of match.")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=20, ge=1, le=MAX_RESULTS)
    current_file: ProjectFilePath | None = Field(
        default=None, description="The open file: results in it and in files related by imports rank higher."
    )
    mode: SearchMode = Field(
        default=SearchMode.DETERMINISTIC,
        description="deterministic (Module 9), semantic (embeddings), or hybrid (both, fused by rank). "
        "Falls back to deterministic, with a warning, when semantic retrieval is unavailable.",
    )


class Snippet(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    lines: list[str]
    truncated: bool = Field(description="True when lines were cut to the snippet size limits.")


class ScoreDetails(BaseModel):
    base: int = Field(description="Weight of the match type.")
    coverage: float = Field(description="Share of query terms matched (1.0 for exact matches).")
    context_bonus: int = Field(description="Bonus for the current file or files related to it by imports.")


class FusionDetails(BaseModel):
    rrf_score: float = Field(description="Sum of 1 / (k + rank) over the lists that contain the result.")
    k: int
    deterministic_rank: int | None
    semantic_rank: int | None


class SearchResult(BaseModel):
    file_path: str
    symbol_name: str | None
    symbol_type: SymbolKind | None
    qualified_name: str | None
    language: Language
    line: int | None
    end_line: int | None
    column: int | None
    score: float = Field(
        description="deterministic: base x coverage + context_bonus (see score_details); "
        "semantic: cosine similarity; hybrid: the RRF score (see fusion)."
    )
    score_details: ScoreDetails | None = Field(
        description="Deterministic scoring, when this was a deterministic match."
    )
    match_type: MatchType
    match_reason: str
    snippet: Snippet | None
    related_symbols: list[str]
    semantic_similarity: float | None = Field(
        default=None, description="Cosine similarity to the query, when found by semantic retrieval."
    )
    fusion: FusionDetails | None = Field(default=None, description="Rank fusion details (hybrid mode).")


class SearchResponse(BaseModel):
    query: str
    terms: list[str] = Field(description="Normalized query terms used for matching.")
    results: list[SearchResult]
    total: int = Field(description="Matches found before `limit` was applied (capped).")
    truncated: bool
    indexed_files: int
    ranking: str = Field(description="How results are ordered.")
    mode: SearchMode = Field(description="The requested mode.")
    mode_used: SearchMode = Field(description="The mode that produced the results.")
    warnings: list[str] = Field(default_factory=list)


class SnippetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: ProjectFilePath
    line: int = Field(ge=1, le=1_000_000)
    before: int = Field(default=5, ge=0, le=20)
    after: int = Field(default=10, ge=0, le=40)


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_file: ProjectFilePath
    query: str | None = Field(default=None, max_length=200)
    line: int | None = Field(default=None, ge=1, le=1_000_000)
    current_symbol: str | None = Field(default=None, max_length=200)
    diagnostics: list[DiagnosticInput] = Field(default_factory=list, max_length=50)


class ContextFile(BaseModel):
    file_path: str
    role: str = Field(description="current | imported | importer | match | semantic")


class ContextSymbol(BaseModel):
    name: str
    qualified_name: str
    kind: SymbolKind
    file_path: str
    line: int
    end_line: int
    signature: str | None


class ContextRelationship(BaseModel):
    source: str
    target: str
    kind: str
    line: int | None


class ContextSnippet(Snippet):
    reason: str


class RelevantContext(BaseModel):
    """Bounded context for one file: deterministic selection, then semantic matches when available."""

    current_file: str
    containing_symbol: ContextSymbol | None
    files: list[ContextFile]
    snippets: list[ContextSnippet]
    symbols: list[ContextSymbol]
    relationships: list[ContextRelationship]
    diagnostics: list[DiagnosticInput]
    metadata: dict[str, Any]
