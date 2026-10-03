"""Semantic retrieval services (Module 10).

``RetrievalService`` (one per application) owns embedding-provider selection,
status, abuse limits, and a small cache of query embeddings. ``SemanticRetriever``
(one per request, for the signed-in user) indexes a project's chunks into
``code_chunks`` and runs similarity searches over them.

Every operation takes a project and its Module 9 ``ProjectIndex``, both obtained
through ``ProjectSearchService.project_index``, which enforces ownership. Queries
are always filtered by ``project_id`` and only return chunks whose content hash
matches the file's current content, so edited files never yield stale locations.
Nothing here reads the filesystem or executes code.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.rate_limit import AttemptLimiter
from app.db.models import CodeChunk, Project, ProjectFile, User
from app.schemas.retrieval import IndexRunResponse, IndexStatusResponse, RetrievalStatusResponse
from app.services.languages import Language
from app.services.project_search.index import IndexedFile, ProjectIndex
from app.services.retrieval.base import (
    EMBEDDING_DIMENSIONS,
    EmbeddingMalformedResponseError,
    EmbeddingProvider,
    InputType,
    RetrievalDisabledError,
    RetrievalError,
    RetrievalNotConfiguredError,
)
from app.services.retrieval.chunking import Chunk, chunk_file
from app.services.retrieval.providers import UnknownEmbeddingProviderError, create_embedding_provider

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 4000
QUERY_CACHE_SIZE = 256
# Texts embedded per provider call during indexing; each group is committed on its own,
# so a failure keeps the progress made so far.
INDEX_GROUP_SIZE = 256


class IndexRunLimitError(AppError):
    status_code = 429
    code = "too_many_index_runs"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many indexing runs. Try again in {retry_after} seconds.")
        self.headers = {"Retry-After": str(retry_after)}


class SemanticQueryError(RetrievalError):
    """The similarity query failed in the database (e.g. pgvector missing or too old)."""

    status_code = 503
    code = "rag_query_failed"

    def __init__(self) -> None:
        super().__init__("The semantic index could not be queried.")


class QueryLimitError(RetrievalError):
    status_code = 429
    code = "too_many_semantic_queries"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many semantic searches. Try again in {retry_after} seconds.")
        self.headers = {"Retry-After": str(retry_after)}


class RetrievalService:
    """Application-wide semantic-retrieval entry point (stored on ``app.state``)."""

    def __init__(self, settings: Settings, provider: EmbeddingProvider | None = None) -> None:
        self.settings = settings
        self.provider: EmbeddingProvider | None = provider
        self.provider_problem: str | None = None
        if provider is None and settings.rag_enabled:
            try:
                self.provider = create_embedding_provider(settings)
            except UnknownEmbeddingProviderError as exc:
                self.provider_problem = f"Unknown embedding provider {exc.args[0]!r} (supported: voyage)."
        if self.provider is not None and self.provider.dimensions != EMBEDDING_DIMENSIONS:
            self.provider_problem = (
                f"The embedding provider produces {self.provider.dimensions}-dimensional vectors; "
                f"the database stores {EMBEDDING_DIMENSIONS}."
            )
        self.query_limiter = AttemptLimiter(settings.rag_max_queries, settings.rag_window_seconds)
        self.index_limiter = AttemptLimiter(settings.rag_max_index_runs, settings.rag_window_seconds)
        self._queries: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def status(self) -> RetrievalStatusResponse:
        enabled = self.settings.rag_enabled
        state = self.provider.status() if self.provider is not None else None
        configured = state is not None and state.configured and self.provider_problem is None
        if not enabled:
            detail: str | None = "Semantic retrieval is turned off (set RAG_ENABLED=true to enable it)."
        elif self.provider_problem:
            detail = self.provider_problem
        elif state is not None and not state.configured:
            detail = state.detail
        else:
            detail = None
        return RetrievalStatusResponse(
            enabled=enabled,
            configured=configured,
            available=enabled and configured,
            provider=state.provider if state else self.settings.rag_embedding_provider,
            model=state.model if state else None,
            dimensions=EMBEDDING_DIMENSIONS,
            detail=detail,
        )

    @property
    def available(self) -> bool:
        return self.status().available

    def require_provider(self) -> EmbeddingProvider:
        if not self.settings.rag_enabled:
            raise RetrievalDisabledError()
        if self.provider is None or self.provider_problem:
            raise RetrievalNotConfiguredError(self.provider_problem or "No embedding provider is configured.")
        state = self.provider.status()
        if not state.configured:
            raise RetrievalNotConfiguredError(state.detail or "The embedding provider is not configured.")
        return self.provider

    def start_index_run(self, user: User) -> EmbeddingProvider:
        provider = self.require_provider()
        key = f"rag-index:{user.id}"
        if (retry_after := self.index_limiter.retry_after(key)) is not None:
            raise IndexRunLimitError(retry_after)
        self.index_limiter.record_failure(key)  # every run counts toward the limit
        return provider

    def embed_query(self, user: User, query: str) -> list[float]:
        """The query's embedding (cached per model and text). Counts toward the user's query limit."""
        provider = self.require_provider()
        cache_key = (provider.model, query[:MAX_QUERY_CHARS])
        with self._lock:
            cached = self._queries.get(cache_key)
            if cached is not None:
                self._queries.move_to_end(cache_key)
                return cached
        key = f"rag-query:{user.id}"
        if (retry_after := self.query_limiter.retry_after(key)) is not None:
            raise QueryLimitError(retry_after)
        self.query_limiter.record_failure(key)
        result = provider.embed([cache_key[1]], InputType.QUERY)
        if len(result.vectors) != 1:
            raise EmbeddingMalformedResponseError()
        vector = result.vectors[0]
        with self._lock:
            self._queries[cache_key] = vector
            while len(self._queries) > QUERY_CACHE_SIZE:
                self._queries.popitem(last=False)
        return vector


@dataclass(frozen=True)
class SemanticHit:
    file_path: str
    start_line: int
    end_line: int
    symbol_name: str | None
    symbol_kind: str | None
    similarity: float


def _indexable(index: ProjectIndex) -> dict[str, IndexedFile]:
    return {
        path: file
        for path, file in index.files.items()
        if file.lines and any(line.strip() for line in file.lines)
    }


class SemanticRetriever:
    """Per-request indexing and similarity search for the signed-in user's projects."""

    def __init__(self, session: Session, settings: Settings, owner: User, service: RetrievalService) -> None:
        self.session = session
        self.settings = settings
        self.owner = owner
        self.service = service

    @property
    def available(self) -> bool:
        return self.service.available

    @property
    def model(self) -> str | None:
        return self.service.provider.model if self.service.provider is not None else None

    # --- status --------------------------------------------------------------------------

    def _current_paths(self, project: Project, model: str) -> set[str]:
        rows = self.session.execute(
            select(ProjectFile.path)
            .join(CodeChunk, CodeChunk.file_id == ProjectFile.id)
            .where(
                CodeChunk.project_id == project.id,
                CodeChunk.embedding_model == model,
                CodeChunk.content_hash == ProjectFile.content_hash,
            )
            .distinct()
        ).scalars()
        return set(rows)

    def index_status(self, project: Project, index: ProjectIndex) -> IndexStatusResponse:
        indexable = _indexable(index)
        model = self.model
        if model is None:
            return IndexStatusResponse(
                available=False,
                model=None,
                indexable_files=len(indexable),
                indexed_files=0,
                stale_files=len(indexable),
                chunks=0,
            )
        current = self._current_paths(project, model) & indexable.keys()
        chunks = self.session.execute(
            select(func.count())
            .select_from(CodeChunk)
            .join(ProjectFile, ProjectFile.id == CodeChunk.file_id)
            .where(
                CodeChunk.project_id == project.id,
                CodeChunk.embedding_model == model,
                CodeChunk.content_hash == ProjectFile.content_hash,
            )
        ).scalar_one()
        return IndexStatusResponse(
            available=self.available,
            model=model,
            indexable_files=len(indexable),
            indexed_files=len(current),
            stale_files=len(indexable) - len(current),
            chunks=chunks,
        )

    # --- indexing ------------------------------------------------------------------------

    def index_project(self, project: Project, index: ProjectIndex) -> IndexRunResponse:
        """Embed new and changed files (incremental, bounded per run)."""
        provider = self.service.start_index_run(self.owner)
        model = provider.model
        indexable = _indexable(index)
        current = self._current_paths(project, model)
        records = {
            path: (file_id, digest)
            for path, file_id, digest in self.session.execute(
                select(ProjectFile.path, ProjectFile.id, ProjectFile.content_hash).where(
                    ProjectFile.project_id == project.id
                )
            ).all()
        }
        stale = sorted(
            path for path in indexable if path not in current and records.get(path, (None, None))[1]
        )

        budget = self.service.settings.rag_max_chunks_per_run
        planned: list[tuple[str, list[Chunk], dict[str, list[float]]]] = []
        needed_total = 0
        for path in stale:
            chunks = chunk_file(indexable[path])
            if not chunks:
                continue
            file_id = records[path][0]
            reusable = dict(
                self.session.execute(
                    select(CodeChunk.chunk_hash, CodeChunk.embedding).where(
                        CodeChunk.file_id == file_id,
                        CodeChunk.embedding_model == model,
                        CodeChunk.chunk_hash.in_([c.hash for c in chunks]),
                    )
                ).all()
            )
            needed = sum(1 for c in chunks if c.hash not in reusable)
            if planned and needed_total + needed > budget:
                break
            planned.append((path, chunks, reusable))
            needed_total += needed

        embedded = reused = tokens = files_done = 0
        group: list[tuple[str, list[Chunk], dict[str, list[float]]]] = []
        group_texts = 0
        for item in planned:
            group.append(item)
            group_texts += sum(1 for c in item[1] if c.hash not in item[2])
            if group_texts >= INDEX_GROUP_SIZE:
                e, r, t = self._write_group(project, model, records, group)
                embedded, reused, tokens, files_done = (
                    embedded + e,
                    reused + r,
                    tokens + t,
                    files_done + len(group),
                )
                group, group_texts = [], 0
        if group:
            e, r, t = self._write_group(project, model, records, group)
            embedded, reused, tokens, files_done = (
                embedded + e,
                reused + r,
                tokens + t,
                files_done + len(group),
            )

        status = self.index_status(project, index)
        logger.info(
            "Indexed project %s: %d files, %d chunks embedded, %d reused, %d tokens",
            project.id,
            files_done,
            embedded,
            reused,
            tokens,
        )
        return IndexRunResponse(
            files_indexed=files_done,
            chunks_embedded=embedded,
            chunks_reused=reused,
            tokens_used=tokens,
            remaining_files=status.stale_files,
            status=status,
        )

    def _write_group(
        self,
        project: Project,
        model: str,
        records: dict[str, tuple[uuid.UUID, str | None]],
        group: list[tuple[str, list[Chunk], dict[str, list[float]]]],
    ) -> tuple[int, int, int]:
        provider = self.service.require_provider()
        texts = [c.text for _, chunks, reusable in group for c in chunks if c.hash not in reusable]
        vectors: list[list[float]] = []
        tokens = 0
        if texts:
            result = provider.embed(texts, InputType.DOCUMENT)
            if len(result.vectors) != len(texts):
                raise EmbeddingMalformedResponseError(
                    "The embedding provider returned the wrong number of vectors."
                )
            vectors, tokens = result.vectors, result.total_tokens
        fresh = iter(vectors)
        reused = 0
        for path, chunks, reusable in group:
            file_id, digest = records[path]
            self.session.execute(
                delete(CodeChunk).where(CodeChunk.file_id == file_id, CodeChunk.embedding_model == model)
            )
            for chunk in chunks:
                vector = reusable.get(chunk.hash)
                if vector is None:
                    vector = next(fresh)
                else:
                    reused += 1
                self.session.add(
                    CodeChunk(
                        project_id=project.id,
                        file_id=file_id,
                        content_hash=digest,
                        chunk_hash=chunk.hash,
                        chunk_index=chunk.index,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        symbol_name=chunk.symbol_name,
                        symbol_kind=chunk.symbol_kind,
                        embedding_model=model,
                        embedding=vector,
                    )
                )
        self.session.commit()
        return len(texts), reused, tokens

    # --- search --------------------------------------------------------------------------

    def _run_similarity_query(self, statement: Select[Any]) -> list[Any]:
        """Run the vector query in a savepoint, so a database failure cannot abort the request's
        transaction (deterministic results, AI history, ... still work); it becomes a
        ``SemanticQueryError`` that callers turn into a deterministic fallback."""
        try:
            with self.session.begin_nested():
                self._tune_hnsw()
                return list(self.session.execute(statement).all())
        except SQLAlchemyError:
            logger.exception("Semantic similarity query failed")
            raise SemanticQueryError() from None

    def _tune_hnsw(self) -> None:
        """Best-effort HNSW settings for this transaction (each in its own savepoint).

        ``iterative_scan`` (pgvector >= 0.8) keeps scanning until enough rows pass the project
        filter; older versions reject it, and the query still runs, possibly with fewer rows.
        """
        for statement in (
            "SET LOCAL hnsw.ef_search = 100",  # candidate list (default 40)
            "SET LOCAL hnsw.iterative_scan = 'relaxed_order'",
        ):
            try:
                with self.session.begin_nested():
                    self.session.execute(text(statement))
            except SQLAlchemyError:
                logger.info("pgvector setting not supported: %s", statement)

    def search(
        self,
        project: Project,
        index: ProjectIndex,
        query: str,
        *,
        limit: int,
        exclude_path: str | None = None,
        language: Language | None = None,
        path_prefix: str | None = None,
        symbol_kind: str | None = None,
    ) -> list[SemanticHit]:
        """The ``limit`` current chunks most similar to ``query``. Raises ``RetrievalError`` subclasses."""
        provider = self.service.require_provider()
        vector = self.service.embed_query(self.owner, query)
        distance = CodeChunk.embedding.cosine_distance(vector)
        statement = (
            select(
                ProjectFile.path,
                CodeChunk.start_line,
                CodeChunk.end_line,
                CodeChunk.symbol_name,
                CodeChunk.symbol_kind,
                distance.label("distance"),
            )
            .join(ProjectFile, ProjectFile.id == CodeChunk.file_id)
            .where(
                CodeChunk.project_id == project.id,
                CodeChunk.embedding_model == provider.model,
                CodeChunk.content_hash == ProjectFile.content_hash,
            )
            .order_by(distance)
            .limit(limit * 2)
        )
        if exclude_path is not None:
            statement = statement.where(ProjectFile.path != exclude_path)
        if language is not None:
            statement = statement.where(ProjectFile.language == language.value)
        if path_prefix is not None:
            statement = statement.where(ProjectFile.path.startswith(f"{path_prefix.rstrip('/')}/"))
        if symbol_kind is not None:
            statement = statement.where(CodeChunk.symbol_kind == symbol_kind)
        rows = self._run_similarity_query(statement)
        hits = [
            SemanticHit(
                file_path=path,
                start_line=start,
                end_line=end,
                symbol_name=symbol,
                symbol_kind=kind,
                similarity=round(1 - float(dist), 4),
            )
            for path, start, end, symbol, kind, dist in rows
            if path in index.files  # ignored and secret files are never returned
        ]
        # relaxed_order may return rows slightly out of order: re-sort exactly.
        hits.sort(key=lambda h: (-h.similarity, h.file_path, h.start_line))
        return hits[:limit]
