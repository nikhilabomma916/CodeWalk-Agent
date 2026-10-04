"""Project-aware search over one user's stored project (Module 9, extended by Module 10).

Search reads only the caller's own project (ownership is checked by
ProjectService) and only stored file records, never the filesystem. Results,
snippets, and response sizes are bounded.

The deterministic search below is the default and is unchanged by Module 10. The
``semantic`` and ``hybrid`` modes add embedding similarity from ``SemanticRetriever``;
hybrid fuses the two ranked lists with reciprocal rank fusion. When semantic
retrieval is unavailable or fails, the response falls back to deterministic
results and says so in ``warnings``.
"""

from __future__ import annotations

import heapq
import logging
import posixpath
import time
import uuid
from collections.abc import Callable, Hashable, Iterator
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.metrics import METRICS, timed
from app.db.models import Project, ProjectFile, User
from app.repositories.files import FileRepository
from app.schemas.search import (
    FusionDetails,
    MatchType,
    ScoreDetails,
    SearchMode,
    SearchRequest,
    SearchResponse,
    SearchResult,
    Snippet,
    SnippetRequest,
)
from app.services.languages import detect_language
from app.services.project_intelligence.models import CodeSymbol, FileStructure, SymbolKind
from app.services.project_intelligence.project_analyzer import STRUCTURE_LANGUAGES
from app.services.project_intelligence.service import stored_structure
from app.services.project_search import ranking
from app.services.project_search.index import (
    IndexCache,
    IndexedFile,
    LoadedFile,
    ProjectIndex,
    fingerprint_of,
)
from app.services.projects import ProjectService
from app.services.retrieval import fusion
from app.services.retrieval.base import RetrievalError

if TYPE_CHECKING:
    from app.services.retrieval.service import SemanticHit, SemanticRetriever

logger = logging.getLogger(__name__)

MAX_SNIPPET_LINES = 12
MAX_LINE_CHARS = 300
MAX_TEXT_MATCHES_PER_FILE = 5
MAX_CANDIDATES = 1000
MAX_RELATED_SYMBOLS = 8
# List lengths fed into rank fusion (hybrid mode).
FUSE_DETERMINISTIC = 50
FUSE_SEMANTIC = 20


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


class Candidate(NamedTuple):
    """A deterministic match before its result is built: ranking needs only the sort key, and the
    full result (snippet, related symbols) is built only for matches that are returned."""

    key: tuple[float, str, int]
    match_type: MatchType
    build: Callable[[], SearchResult]


def loaded_file(record: ProjectFile) -> LoadedFile:
    """A stored file's content and structure for the search index. The structure comes from the
    per-file cache and is written back to the record when it had to be extracted (the caller commits)."""
    language = detect_language(record.path)
    structure = FileStructure()
    if record.content is not None and language in STRUCTURE_LANGUAGES:
        try:
            structure = stored_structure(record, language)
        except Exception:
            logger.exception("Structure extraction crashed for a %s file", language.value)
    return LoadedFile(
        path=record.path, content_hash=record.content_hash, content=record.content, structure=structure
    )


def related_symbols(file: IndexedFile, symbol: CodeSymbol | None) -> list[str]:
    if symbol is None:
        names = [s.qualified_name for s in file.symbols if s.parent is None]
    else:
        names = [s.qualified_name for s in file.symbols if s.id == symbol.parent or s.parent == symbol.id]
    return names[:MAX_RELATED_SYMBOLS]


class ProjectSearchService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        owner: User,
        cache: IndexCache,
        retriever: SemanticRetriever | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.owner = owner
        self.cache = cache
        self.retriever = retriever
        self.projects = ProjectService(session, settings, owner)
        self.files = FileRepository(session)

    # --- index ---------------------------------------------------------------------------

    def index_for(self, project: Project) -> ProjectIndex:
        hashes: dict[str, str | None] = dict(
            self.session.execute(
                select(ProjectFile.path, ProjectFile.content_hash)
                .where(ProjectFile.project_id == project.id)
                .order_by(ProjectFile.path)
            ).all()
        )
        fingerprint = fingerprint_of(list(hashes.items()))
        cached = self.cache.get(project.id, fingerprint)
        if cached is not None:
            return cached
        # Reuse the previous index of this project: only new and changed files are read and parsed.
        started = time.perf_counter()
        previous = self.cache.latest(project.id)
        stale = previous.stale_paths(hashes) if previous is not None else list(hashes)
        if previous is None or len(stale) > len(hashes) // 2:
            previous = None
            loaded = {record.path: loaded_file(record) for record in self.files.list_all(project.id)}
            hashes = {path: file.content_hash for path, file in loaded.items()}
        else:
            loaded = {
                record.path: loaded_file(record) for record in self.files.list_by_paths(project.id, stale)
            }
            # A file changed or deleted after the hash query is indexed as it was read.
            for path in stale:
                if path in loaded:
                    hashes[path] = loaded[path].content_hash
                else:
                    del hashes[path]
        self.session.commit()  # keep structures computed for changed files in the per-file cache
        index = ProjectIndex.assemble(hashes, loaded, previous)
        self.cache.put(project.id, index.fingerprint, index)
        METRICS.observe(
            "search_index_build", time.perf_counter() - started, "full" if previous is None else "incremental"
        )
        return index

    def project_index(self, project_id: uuid.UUID) -> tuple[Project, ProjectIndex]:
        project = self.projects.get(project_id)  # 404 for other users' projects
        return project, self.index_for(project)

    # --- search --------------------------------------------------------------------------

    def search(self, project_id: uuid.UUID, request: SearchRequest) -> SearchResponse:
        with timed("search") as metric:
            response = self._search(project_id, request)
            metric["outcome"] = response.mode_used.value
            return response

    def _search(self, project_id: uuid.UUID, request: SearchRequest) -> SearchResponse:
        project, index = self.project_index(project_id)
        query = request.query.strip()
        query_terms = ranking.terms(query)
        if request.current_file is not None and request.current_file not in index.files:
            raise NotFoundError("The current file is not part of this project.", code="file_not_found")
        related = index.related_to(request.current_file) if request.current_file else set()

        def bonus(path: str) -> int:
            if path == request.current_file:
                return ranking.CURRENT_FILE_BONUS
            return ranking.RELATED_FILE_BONUS if path in related else 0

        def deterministic() -> tuple[list[SearchResult], int]:
            """The best matches in every file (the top MAX_CANDIDATES are kept, so a strong match in a
            late file is never lost), built for as many as can be used, and the number kept."""
            allowed = set(request.filters.match_types or MatchType)
            found = (
                candidate
                for file in self._filtered_files(index, request)
                for candidate in self._match_file(file, query, query_terms, request, bonus(file.path))
                if candidate.match_type in allowed
            )
            best = heapq.nsmallest(MAX_CANDIDATES, found, key=lambda candidate: candidate.key)
            return [c.build() for c in best[: max(request.limit, FUSE_DETERMINISTIC)]], len(best)

        warnings: list[str] = []

        def respond(
            results: list[SearchResult], mode_used: SearchMode, description: str, total: int | None = None
        ) -> SearchResponse:
            total = len(results) if total is None else total
            return SearchResponse(
                query=query,
                terms=query_terms,
                results=results[: request.limit],
                total=total,
                truncated=total > request.limit,
                indexed_files=len(index.files),
                ranking=description,
                mode=request.mode,
                mode_used=mode_used,
                warnings=warnings,
            )

        if request.mode is SearchMode.DETERMINISTIC:
            results, total = deterministic()
            return respond(results, SearchMode.DETERMINISTIC, ranking.RANKING_DESCRIPTION, total)

        # Deterministic matching runs only when its results are used: hybrid fusion, or the fallback.
        semantic = self._semantic_results(project, index, query, request, warnings)
        if semantic is None:
            results, total = deterministic()
            return respond(results, SearchMode.DETERMINISTIC, ranking.RANKING_DESCRIPTION, total)
        if request.mode is SearchMode.SEMANTIC:
            return respond(semantic, SearchMode.SEMANTIC, self._semantic_description())
        return respond(self._fuse(deterministic()[0], semantic), SearchMode.HYBRID, fusion.DESCRIPTION)

    # --- semantic and hybrid (Module 10) -------------------------------------------------

    def _semantic_description(self) -> str:
        model = self.retriever.model if self.retriever else None
        return (
            f"semantic: cosine similarity between the query and code-chunk embeddings ({model}); "
            "higher is more similar."
        )

    def _semantic_results(
        self, project: Project, index: ProjectIndex, query: str, request: SearchRequest, warnings: list[str]
    ) -> list[SearchResult] | None:
        """Semantic matches as search results, or None (with a warning) when unavailable."""
        allowed = request.filters.match_types
        if allowed is not None and MatchType.SEMANTIC not in allowed:
            warnings.append("Semantic matches were excluded by the match_types filter.")
            return None
        if self.retriever is None or not self.retriever.available:
            status = self.retriever.service.status() if self.retriever else None
            detail = status.detail if status and status.detail else "Semantic retrieval is not available."
            warnings.append(f"{detail} Showing deterministic results.")
            return None
        filters = request.filters
        try:
            hits = self.retriever.search(
                project,
                index,
                query,
                limit=max(request.limit, FUSE_SEMANTIC),
                language=filters.language,
                path_prefix=filters.path_prefix,
                symbol_kind=filters.symbol_type.value if filters.symbol_type else None,
            )
        except RetrievalError as exc:
            warnings.append(f"Semantic retrieval failed: {exc.message} Showing deterministic results.")
            return None
        coverage = self.retriever.index_status(project, index)
        if coverage.indexed_files == 0:
            warnings.append("This project has no semantic index yet: index it to get semantic matches.")
        elif coverage.stale_files:
            warnings.append(
                f"{coverage.stale_files} file(s) changed since the last indexing; their semantic matches are "
                "missing until the project is indexed again."
            )
        return [self._semantic_result(index, hit) for hit in hits]

    @staticmethod
    def _semantic_result(index: ProjectIndex, hit: SemanticHit) -> SearchResult:
        file = index.files[hit.file_path]
        named = [s for s in file.symbols if s.qualified_name == hit.symbol_name]
        symbol = next((s for s in named if hit.start_line <= s.line <= hit.end_line), None) or next(
            iter(named), None
        )
        kind = symbol.kind if symbol else (SymbolKind(hit.symbol_kind) if hit.symbol_kind else None)
        return SearchResult(
            file_path=file.path,
            symbol_name=symbol.name if symbol else None,
            symbol_type=kind,
            qualified_name=hit.symbol_name,
            language=file.language,
            line=hit.start_line,
            end_line=hit.end_line,
            column=symbol.column if symbol and symbol.line == hit.start_line else 1,
            score=hit.similarity,
            score_details=None,
            match_type=MatchType.SEMANTIC,
            match_reason=f"semantically similar to the query (cosine similarity {hit.similarity:.3f})",
            snippet=make_snippet(file, hit.start_line, hit.end_line),
            related_symbols=related_symbols(file, symbol),
            semantic_similarity=hit.similarity,
        )

    @staticmethod
    def _fuse(deterministic: list[SearchResult], semantic: list[SearchResult]) -> list[SearchResult]:
        """Reciprocal rank fusion; a location found by both lists becomes one result."""
        by_key: dict[Hashable, SearchResult] = {}
        det_keys: list[Hashable] = []
        for position, result in enumerate(deterministic[:FUSE_DETERMINISTIC]):
            key: Hashable = (result.file_path, result.line)
            if key in by_key:
                key = (result.file_path, result.line, position)  # a second match on the same line
            by_key[key] = result
            det_keys.append(key)
        sem_keys: list[Hashable] = []
        similarity: dict[Hashable, float] = {}
        for result in semantic[:FUSE_SEMANTIC]:
            key = (result.file_path, result.line)
            sem_keys.append(key)
            similarity.setdefault(key, result.semantic_similarity or 0.0)
            by_key.setdefault(key, result)
        fused: list[SearchResult] = []
        for item in fusion.rrf(det_keys, sem_keys):
            base = by_key[item.key]
            fused.append(
                base.model_copy(
                    update={
                        "score": round(item.score, 6),
                        "semantic_similarity": similarity.get(item.key, base.semantic_similarity),
                        "fusion": FusionDetails(
                            rrf_score=round(item.score, 6),
                            k=fusion.K,
                            deterministic_rank=item.deterministic_rank,
                            semantic_rank=item.semantic_rank,
                        ),
                    }
                )
            )
        return fused

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
    ) -> Iterator[Candidate]:
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
        ) -> Candidate:
            score = ranking.score(match_type, share, bonus)

            def build() -> SearchResult:
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
                    score=score,
                    score_details=ScoreDetails(
                        base=ranking.BASE[match_type], coverage=round(share, 3), context_bonus=bonus
                    ),
                    match_type=match_type,
                    match_reason=reason,
                    snippet=snippet,
                    related_symbols=related_symbols(file, symbol),
                )

            return Candidate((-score, file.path, line or 0), match_type, build)

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
        # Whole-file pre-check (C-speed string operations): a line can only match if the file as a
        # whole contains the phrase, every term, or the compacted identifier. Files that cannot
        # match skip the per-line loop; results are identical.
        whole = "\n".join(file.lines).lower()
        if not (
            phrase in whole
            or (query_terms and all(t in whole for t in query_terms))
            or (target in ranking.compact(whole) if target else True)
        ):
            return
        found = 0
        for number, text in enumerate(file.lines, start=1):
            if found >= MAX_TEXT_MATCHES_PER_FILE:
                break
            if number in symbol_lines:
                continue
            lowered = text.lower()
            # An identifier compacts to the target only if the target appears in the line once
            # underscores are removed: check that (C-speed) before running the identifier regex.
            identifier = (
                next(
                    (m for m in ranking.IDENTIFIER.finditer(text) if ranking.compact(m.group()) == target),
                    None,
                )
                if not target or target in lowered.replace("_", "")
                else None
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
