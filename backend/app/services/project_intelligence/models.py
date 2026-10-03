"""Structured, deterministic project intelligence (no AI)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.services.languages import Language

# Bump when extraction output changes so cached per-file structures are recomputed.
STRUCTURE_VERSION = 1


class SymbolKind(StrEnum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    VARIABLE = "variable"


class CodeSymbol(BaseModel):
    id: str = Field(description="Stable id: '<file path>::<qualified name>'.")
    name: str
    qualified_name: str
    kind: SymbolKind
    file_path: str
    line: int
    column: int
    end_line: int
    end_column: int
    parent: str | None = Field(default=None, description="Id of the enclosing symbol.")
    signature: str | None = None
    is_async: bool = False
    decorators: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    return_annotation: str | None = None
    exported: bool | None = Field(default=None, description="JS/TS only: declared with 'export'.")


class ImportKind(StrEnum):
    IMPORT = "import"
    FROM_IMPORT = "from_import"
    REQUIRE = "require"
    DYNAMIC = "dynamic_import"
    REEXPORT = "reexport"


class ImportRecord(BaseModel):
    module: str = Field(description="Module name or specifier as written, e.g. 'app.core' or './api'.")
    names: list[str] = Field(default_factory=list)
    kind: ImportKind
    line: int
    level: int = Field(default=0, description="Python relative-import level (number of leading dots).")
    resolved_path: str | None = Field(default=None, description="Project file the import resolves to.")


class FileStructure(BaseModel):
    """Per-file extraction output (cached in the database per content hash)."""

    symbols: list[CodeSymbol] = Field(default_factory=list)
    imports: list[ImportRecord] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    parse_error: str | None = None


class ProjectFileInfo(BaseModel):
    path: str
    name: str
    extension: str
    language: Language
    size: int
    line_count: int
    symbols: list[CodeSymbol]
    imports: list[ImportRecord]
    exports: list[str]
    structure_supported: bool = Field(description="Whether symbols/imports are extracted for this language.")
    skipped_reason: str | None = Field(
        default=None, description="Why content was not analyzed, if it was not."
    )


class RelationshipKind(StrEnum):
    IMPORTS = "imports"
    DEFINES = "defines"
    CONTAINS = "contains"


class TargetKind(StrEnum):
    FILE = "file"
    MODULE = "module"
    SYMBOL = "symbol"


class Relationship(BaseModel):
    source: str
    target: str
    kind: RelationshipKind
    target_kind: TargetKind
    line: int | None = None


class FileError(BaseModel):
    path: str
    stage: str = Field(description="'read' or 'parse'.")
    message: str


class LanguageStat(BaseModel):
    language: Language
    files: int
    lines: int
    bytes: int


class LargestFile(BaseModel):
    path: str
    size: int
    line_count: int


class ProjectStatistics(BaseModel):
    total_files: int
    total_directories: int
    total_lines: int
    total_bytes: int
    languages: list[LanguageStat]
    largest_files: list[LargestFile]
    symbol_counts: dict[str, int]
    total_symbols: int
    total_imports: int
    internal_imports: int
    external_imports: int
    analysis_errors: int
    skipped_files: int


class SyncSummary(BaseModel):
    """What a rescan of a linked folder changed in the stored files."""

    created: int
    updated: int
    deleted: int
    unchanged: int


class ProjectSummary(BaseModel):
    id: str | None
    name: str
    root_path: str | None


class ProjectAnalysisResult(BaseModel):
    project: ProjectSummary
    files: list[ProjectFileInfo]
    directories: list[str]
    relationships: list[Relationship]
    statistics: ProjectStatistics
    errors: list[FileError]
    analysis_id: str | None = None
    analyzed_at: datetime
    duration_ms: float
    sync: SyncSummary | None = None


@dataclass(frozen=True)
class SourceFile:
    """A file handed to the analyzer; ``content`` is None when it was not read."""

    path: str
    size: int
    content: str | None
    skipped_reason: str | None = None
