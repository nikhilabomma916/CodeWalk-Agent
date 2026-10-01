"""Project-aware search over one user's stored project (Module 9).

Search reads only the caller's own project (ownership is checked by
ProjectService) and only stored file records, never the filesystem. Results,
snippets, and response sizes are bounded.
"""

from __future__ import annotations

import posixpath
import uuid
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.db.models import Project, ProjectFile, User
from app.repositories.files import FileRepository
from app.schemas.search import (
    MatchType,
    ScoreDetails,
    SearchRequest,
    SearchResponse,
    SearchResult,
    Snippet,
    SnippetRequest,
)
from app.services.project_intelligence.models import CodeSymbol
from app.services.project_intelligence.service import ProjectIntelligenceService
from app.services.project_search import ranking
from app.services.project_search.index import IndexCache, IndexedFile, ProjectIndex, fingerprint_of
from app.services.projects import ProjectService

MAX_SNIPPET_LINES = 12
MAX_LINE_CHARS = 300
MAX_TEXT_MATCHES_PER_FILE = 5
MAX_CANDIDATES = 1000
MAX_RELATED_SYMBOLS = 8


def make_snippet(
    file: IndexedFile, start: int, end: int, max_lines: int = MAX_SNIPPET_LINES
) -> Snippet | None:
    """Lines start..end (1-based, inclusive), clamped to the file and to the size limits."""
    if file.lines is None or not file.lines:
        return None
    start = max(1, min(start, len(file.lines)))
    end = max(start, min(end, len(file.lines)))
    truncated = end - start + 1 > max_lines
    end = min(end, start + max_lines - 1)
    lines = []
    for text in file.lines[start - 1 : end]:
        if len(text) > MAX_LINE_CHARS:
            truncated = True
            text = text[:MAX_LINE_CHARS] + "…"
        lines.append(text)
    return Snippet(file_path=file.path, start_line=start, end_line=end, lines=lines, truncated=truncated)


def related_symbols(file: IndexedFile, symbol: CodeSymbol | None) -> list[str]:
    if symbol is None:
        names = [s.qualified_name for s in file.symbols if s.parent is None]
    else:
        names = [s.qualified_name for s in file.symbols if s.id == symbol.parent or s.parent == symbol.id]
    return names[:MAX_RELATED_SYMBOLS]


class ProjectSearchService:
    def __init__(self, session: Session, settings: Settings, owner: User, cache: IndexCache) -> None:
        self.session = session
        self.settings = settings
        self.owner = owner
        self.cache = cache
        self.projects = ProjectService(session, settings, owner)
        self.files = FileRepository(session)

    # --- index ---------------------------------------------------------------------------

    def index_for(self, project: Project) -> ProjectIndex:
        pairs = self.session.execute(
            select(ProjectFile.path, ProjectFile.content_hash).where(ProjectFile.project_id == project.id)
        ).all()
        fingerprint = fingerprint_of([(path, digest) for path, digest in pairs])
        cached = self.cache.get(project.id, fingerprint)
        if cached is not None:
            return cached
        records = self.files.list_all(project.id)
        structure = ProjectIntelligenceService(self.session, self.settings, self.owner).structure_of(
            project, records
        )
        self.session.commit()  # keep structures computed for changed files in the per-file cache
        index = ProjectIndex.build(structure, {r.path: r.content for r in records})
        self.cache.put(project.id, fingerprint, index)
        return index

    def project_index(self, project_id: uuid.UUID) -> tuple[Project, ProjectIndex]:
        project = self.projects.get(project_id)  # 404 for other users' projects
        return project, self.index_for(project)

    # --- search --------------------------------------------------------------------------

    def search(self, project_id: uuid.UUID, request: SearchRequest) -> SearchResponse:
        _, index = self.project_index(project_id)
        query = request.query.strip()
        query_terms = ranking.terms(query)
        if request.current_file is not None and request.current_file not in index.files:
            raise NotFoundError("The current file is not part of this project.", code="file_not_found")
        related = index.related_to(request.current_file) if request.current_file else set()

        def bonus(path: str) -> int:
            if path == request.current_file:
                return ranking.CURRENT_FILE_BONUS
            return ranking.RELATED_FILE_BONUS if path in related else 0

        allowed = set(request.filters.match_types or MatchType)
        candidates: list[SearchResult] = []
        for file in self._filtered_files(index, request):
            for result in self._match_file(file, query, query_terms, request, bonus(file.path)):
                if result.match_type in allowed:
                    candidates.append(result)
            if len(candidates) >= MAX_CANDIDATES:
                break
        candidates.sort(key=lambda r: (-r.score, r.file_path, r.line or 0))
        return SearchResponse(
            query=query,
            terms=query_terms,
            results=candidates[: request.limit],
            total=len(candidates),
            truncated=len(candidates) > request.limit,
            indexed_files=len(index.files),
            ranking=ranking.RANKING_DESCRIPTION,
        )

    @staticmethod
    def _filtered_files(index: ProjectIndex, request: SearchRequest) -> Iterator[IndexedFile]:
        filters = request.filters
        prefix = f"{filters.path_prefix.rstrip('/')}/" if filters.path_prefix else None
        for file in index.files.values():
            if filters.language is not None and file.language is not filters.language:
                continue
            if prefix is not None and not file.path.startswith(prefix):
                continue
            yield file

    def _match_file(
        self, file: IndexedFile, query: str, query_terms: list[str], request: SearchRequest, bonus: int
    ) -> Iterator[SearchResult]:
        symbol_type = request.filters.symbol_type
        symbol_lines: set[int] = set()

        def result(
            match_type: MatchType,
            share: float,
            reason: str,
            *,
            symbol: CodeSymbol | None = None,
            line: int | None = None,
            end_line: int | None = None,
            column: int | None = None,
        ) -> SearchResult:
            snippet = None
            if line is not None:
                end = end_line if symbol is not None and end_line else line + 3
                start = line if symbol is not None else max(1, line - 2)
                snippet = make_snippet(file, start, end)
            return SearchResult(
                file_path=file.path,
                symbol_name=symbol.name if symbol else None,
                symbol_type=symbol.kind if symbol else None,
                qualified_name=symbol.qualified_name if symbol else None,
                language=file.language,
                line=line,
                end_line=end_line,
                column=column,
                score=ranking.score(match_type, share, bonus),
                score_details=ScoreDetails(
                    base=ranking.BASE[match_type], coverage=round(share, 3), context_bonus=bonus
                ),
                match_type=match_type,
                match_reason=reason,
                snippet=snippet,
                related_symbols=related_symbols(file, symbol),
            )

        # Symbols (functions, classes, methods, ...) from project intelligence.
        for symbol in file.symbols:
            if symbol_type is not None and symbol.kind is not symbol_type:
                continue
            match = ranking.match_name(query, query_terms, symbol.name)
            if match is None and symbol.qualified_name != symbol.name:
                match = ranking.match_name(query, query_terms, symbol.qualified_name)
            if match is None:
                continue
            match_type, share, reason = match
            symbol_lines.add(symbol.line)
            yield result(
                match_type,
                share,
                f"{symbol.kind.value} {reason}",
                symbol=symbol,
                line=symbol.line,
                end_line=symbol.end_line,
                column=symbol.column,
            )
        if symbol_type is not None:
            return  # a symbol-type filter means symbols only

        # File name and path.
        stem = posixpath.splitext(file.name)[0]
        if query.lower() in (file.name.lower(), stem.lower()) or ranking.compact(query) == ranking.compact(
            stem
        ):
            yield result(MatchType.FILE_NAME, 1.0, "file name equals the query")
        else:
            share = ranking.coverage(query_terms, ranking.terms(file.path))
            if share > 0:
                yield result(MatchType.FILE_PATH, share, "path contains query terms")

        # Imports.
        for record in file.imports:
            names = [record.module, *record.names]
            share = max(ranking.coverage(query_terms, ranking.terms(name)) for name in names)
            if share > 0:
                yield result(MatchType.IMPORT, share, f"imports {record.module}", line=record.line, column=1)

        # Identifiers and text, line by line (bounded per file).
        if file.lines is None:
            return
        target = ranking.compact(query)
        phrase = query.lower()
        found = 0
        for number, text in enumerate(file.lines, start=1):
            if found >= MAX_TEXT_MATCHES_PER_FILE:
                break
            if number in symbol_lines:
                continue
            identifier = next(
                (m for m in ranking.IDENTIFIER.finditer(text) if ranking.compact(m.group()) == target), None
            )
            if identifier is not None:
                found += 1
                yield result(
                    MatchType.IDENTIFIER,
                    1.0,
                    f"identifier {identifier.group()}",
                    line=number,
                    column=identifier.start() + 1,
                )
                continue
            lowered = text.lower()
            if phrase in lowered or (query_terms and all(t in lowered for t in query_terms)):
                found += 1
                position = lowered.find(query_terms[0] if query_terms else phrase)
                yield result(
                    MatchType.TEXT, 1.0, "line contains every query term", line=number, column=position + 1
                )

    # --- snippets ------------------------------------------------------------------------

    def snippet(self, project_id: uuid.UUID, request: SnippetRequest) -> Snippet:
        _, index = self.project_index(project_id)
        file = index.files.get(request.file_path)
        if file is None:
            raise NotFoundError("File not found in this project.", code="file_not_found")
        if file.lines is None:
            raise NotFoundError("This file's content is not stored (binary or too large).", code="no_content")
        if request.line > max(len(file.lines), 1):
            raise NotFoundError("The line is outside the file.", code="line_out_of_range")
        snippet = make_snippet(
            file,
            request.line - request.before,
            request.line + request.after,
            max_lines=request.before + request.after + 1,
        )
        return snippet or Snippet(file_path=file.path, start_line=1, end_line=1, lines=[], truncated=False)
