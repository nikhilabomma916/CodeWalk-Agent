"""Builds a ProjectAnalysisResult from a set of project files.

Works on in-memory file contents, so the same pipeline serves scanned folders
and database-stored projects. One unparsable file never stops the analysis:
its error is recorded and the remaining files are still analyzed.
"""

from __future__ import annotations

import logging
import posixpath
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from app.services.languages import Language, detect_language
from app.services.project_intelligence.javascript_structure import extract_javascript_structure
from app.services.project_intelligence.models import (
    FileError,
    FileStructure,
    LanguageStat,
    LargestFile,
    ProjectAnalysisResult,
    ProjectFileInfo,
    ProjectStatistics,
    ProjectSummary,
    SourceFile,
)
from app.services.project_intelligence.python_structure import extract_python_structure
from app.services.project_intelligence.relationships import JS_LANGUAGES, build_relationships

logger = logging.getLogger(__name__)

STRUCTURE_LANGUAGES = frozenset({Language.PYTHON, *JS_LANGUAGES})
LARGEST_FILES_COUNT = 10

StructureProvider = Callable[[SourceFile, Language], FileStructure]


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def extract_structure(file: SourceFile, language: Language) -> FileStructure:
    if file.content is None:
        raise ValueError(f"{file.path} has no content to analyze")
    if language is Language.PYTHON:
        return extract_python_structure(file.path, file.content)
    return extract_javascript_structure(file.path, file.content, language)


def derive_directories(paths: Sequence[str]) -> list[str]:
    directories: set[str] = set()
    for path in paths:
        parent = posixpath.dirname(path)
        while parent:
            directories.add(parent)
            parent = posixpath.dirname(parent)
    return sorted(directories)


def analyze_project(
    *,
    project: ProjectSummary,
    files: Sequence[SourceFile],
    directories: Sequence[str] | None = None,
    skipped_count: int = 0,
    structure_provider: StructureProvider = extract_structure,
) -> ProjectAnalysisResult:
    started = time.perf_counter()
    languages: dict[str, Language] = {}
    structures: dict[str, FileStructure] = {}
    errors: list[FileError] = []
    contents = {file.path: file.content for file in files}

    for file in files:
        language = detect_language(file.path)
        languages[file.path] = language
        if file.content is None or language not in STRUCTURE_LANGUAGES:
            continue
        try:
            structure = structure_provider(file, language)
        except Exception:
            logger.exception("Structure extraction crashed for a %s file", language.value)
            errors.append(FileError(path=file.path, stage="parse", message="Structure extraction failed"))
            continue
        structures[file.path] = structure
        if structure.parse_error:
            errors.append(FileError(path=file.path, stage="parse", message=structure.parse_error))

    relationships = build_relationships(structures, languages, contents)
    directory_list = (
        list(directories) if directories is not None else derive_directories([f.path for f in files])
    )

    infos: list[ProjectFileInfo] = []
    for file in files:
        language = languages[file.path]
        structure = structures.get(file.path, FileStructure())
        name = posixpath.basename(file.path)
        infos.append(
            ProjectFileInfo(
                path=file.path,
                name=name,
                extension=posixpath.splitext(name)[1].lower(),
                language=language,
                size=file.size,
                line_count=count_lines(file.content or ""),
                symbols=structure.symbols,
                imports=structure.imports,
                exports=structure.exports,
                structure_supported=language in STRUCTURE_LANGUAGES,
                skipped_reason=file.skipped_reason,
            )
        )

    return ProjectAnalysisResult(
        project=project,
        files=infos,
        directories=directory_list,
        relationships=relationships,
        statistics=_statistics(infos, len(directory_list), errors, skipped_count),
        errors=errors,
        analyzed_at=datetime.now(UTC),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _statistics(
    infos: Sequence[ProjectFileInfo],
    directory_count: int,
    errors: Sequence[FileError],
    skipped_count: int,
) -> ProjectStatistics:
    by_language: dict[Language, list[ProjectFileInfo]] = {}
    for info in infos:
        by_language.setdefault(info.language, []).append(info)
    languages = sorted(
        (
            LanguageStat(
                language=language,
                files=len(items),
                lines=sum(i.line_count for i in items),
                bytes=sum(i.size for i in items),
            )
            for language, items in by_language.items()
        ),
        key=lambda stat: (-stat.files, stat.language.value),
    )
    largest = sorted(infos, key=lambda info: (-info.size, info.path))[:LARGEST_FILES_COUNT]
    symbol_counts = Counter(symbol.kind.value for info in infos for symbol in info.symbols)
    all_imports = [record for info in infos for record in info.imports]
    internal = sum(1 for record in all_imports if record.resolved_path)
    return ProjectStatistics(
        total_files=len(infos),
        total_directories=directory_count,
        total_lines=sum(info.line_count for info in infos),
        total_bytes=sum(info.size for info in infos),
        languages=languages,
        largest_files=[LargestFile(path=i.path, size=i.size, line_count=i.line_count) for i in largest],
        symbol_counts=dict(sorted(symbol_counts.items())),
        total_symbols=sum(symbol_counts.values()),
        total_imports=len(all_imports),
        internal_imports=internal,
        external_imports=len(all_imports) - internal,
        analysis_errors=len(errors),
        skipped_files=skipped_count,
    )
