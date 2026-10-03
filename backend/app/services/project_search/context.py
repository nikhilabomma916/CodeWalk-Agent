"""ProjectContextBuilder: bounded context around one file (Module 9, extended by Module 10).

Given the open file (optionally its unsaved buffer), a line, diagnostics, and a
query, it selects related project code in a fixed priority order:

1. definitions, in other files, of names quoted in the diagnostics
   (e.g. ``'total' is not defined``),
2. symbols matching the query / current symbol (project search),
3. definitions of the names the current file imports from project files,
4. the import lines of files that import the current file,
5. (Module 10, when semantic retrieval is available) code in other files whose
   embeddings are most similar to the diagnostics, query, and the code around
   the line.

The deterministic steps always run first; semantic matches only fill the space
they leave. Selection stops at MAX_SNIPPETS or MAX_CONTEXT_CHARS;
``metadata.truncated`` says so. A semantic failure never fails the build: the
context stays deterministic and ``metadata.semantic`` says why.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence

from app.core.exceptions import NotFoundError
from app.db.models import Project
from app.schemas.ai import DiagnosticInput
from app.schemas.search import (
    ContextFile,
    ContextRelationship,
    ContextSnippet,
    ContextSymbol,
    RelevantContext,
    SearchFilters,
    SearchRequest,
)
from app.services.languages import detect_language
from app.services.project_intelligence.models import CodeSymbol, SourceFile
from app.services.project_intelligence.project_analyzer import STRUCTURE_LANGUAGES, extract_structure
from app.services.project_search.index import IndexedFile, ProjectIndex
from app.services.project_search.service import ProjectSearchService, make_snippet
from app.services.retrieval.base import RetrievalError

MAX_SNIPPETS = 8
MAX_CONTEXT_CHARS = 12_000
MAX_DEFINITION_LINES = 30
SEMANTIC_CANDIDATES = 4
MAX_SEMANTIC_QUERY_CHARS = 2000
logger = logging.getLogger(__name__)
_QUOTED_NAME = re.compile(r"['\"`]([A-Za-z_][A-Za-z0-9_]*)['\"`]")


def _symbol(symbol: CodeSymbol) -> ContextSymbol:
    return ContextSymbol(
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        kind=symbol.kind,
        file_path=symbol.file_path,
        line=symbol.line,
        end_line=symbol.end_line,
        signature=symbol.signature,
    )


def containing_symbol(symbols: Sequence[CodeSymbol], line: int) -> CodeSymbol | None:
    """The innermost symbol whose range includes ``line``."""
    enclosing = [s for s in symbols if s.line <= line <= s.end_line]
    return min(enclosing, key=lambda s: s.end_line - s.line, default=None)


def quoted_names(diagnostics: Sequence[DiagnosticInput]) -> list[str]:
    names: list[str] = []
    for diagnostic in diagnostics:
        for name in _QUOTED_NAME.findall(diagnostic.message):
            if name not in names:
                names.append(name)
    return names


class ProjectContextBuilder:
    def __init__(self, search: ProjectSearchService) -> None:
        self.search = search

    def build(
        self,
        project_id: uuid.UUID,
        *,
        current_file: str,
        current_content: str | None = None,
        line: int | None = None,
        query: str | None = None,
        current_symbol: str | None = None,
        diagnostics: Sequence[DiagnosticInput] = (),
    ) -> RelevantContext:
        project, index = self.search.project_index(project_id)
        stored = index.files.get(current_file)
        if stored is None:
            raise NotFoundError("The file is not part of this project.", code="file_not_found")

        symbols = stored.symbols
        language = detect_language(current_file)
        if current_content is not None and language in STRUCTURE_LANGUAGES:
            # The unsaved buffer may differ from the stored file: use its own structure.
            structure = extract_structure(
                SourceFile(path=current_file, size=len(current_content), content=current_content), language
            )
            if structure.parse_error is None:
                symbols = structure.symbols
        container = containing_symbol(symbols, line) if line is not None else None
        source_lines = current_content.splitlines() if current_content is not None else (stored.lines or [])

        selection = _Selection()
        files = [ContextFile(file_path=current_file, role="current")]

        # 1. Definitions of names quoted in diagnostics.
        for name in quoted_names(diagnostics):
            for file, symbol in self._definitions(index, name, exclude=current_file):
                selection.add_definition(file, symbol, f"defines '{name}' (named in a diagnostic)")

        # 2. Query / current symbol matches.
        for text in [t for t in (query, current_symbol) if t and t.strip()]:
            found = self.search.search(
                project_id,
                SearchRequest(query=text, limit=5, current_file=current_file, filters=SearchFilters()),
            )
            for result in found.results:
                match = index.files.get(result.file_path)
                if match is None or result.file_path == current_file or result.line is None:
                    continue
                end = result.end_line if result.symbol_name else result.line + 3
                selection.add_lines(match, result.line, end or result.line, f"matches '{text.strip()}'")

        # 3. What the current file imports from the project.
        for record in stored.imports:
            target = index.files.get(record.resolved_path) if record.resolved_path else None
            if target is None:
                continue
            files.append(ContextFile(file_path=target.path, role="imported"))
            wanted = [s for s in target.symbols if s.name in record.names]
            if wanted:
                for symbol in wanted:
                    selection.add_definition(target, symbol, f"imported at line {record.line}")
            else:
                selection.add_lines(target, 1, 12, f"module imported at line {record.line}")

        # 4. Files that import the current file.
        for importer_path in sorted(index.imported_by.get(current_file, set())):
            importer = index.files[importer_path]
            files.append(ContextFile(file_path=importer_path, role="importer"))
            for record in importer.imports:
                if record.resolved_path == current_file:
                    selection.add_lines(importer, record.line, record.line, "imports the current file")
                    break

        # 5. Semantic matches (Module 10), within the space the deterministic steps left.
        semantic = self._semantic(
            project,
            index,
            selection,
            current_file=current_file,
            text=self._semantic_query(diagnostics, query, current_symbol, container, source_lines, line),
        )

        relationships = [
            ContextRelationship(source=current_file, target=target, kind="imports", line=None)
            for target in sorted(index.imports_of.get(current_file, set()))
        ] + [
            ContextRelationship(source=source, target=current_file, kind="imports", line=None)
            for source in sorted(index.imported_by.get(current_file, set()))
        ]
        for snippet in selection.snippets:
            if all(f.file_path != snippet.file_path for f in files):
                role = "semantic" if snippet.reason.startswith("semantically") else "match"
                files.append(ContextFile(file_path=snippet.file_path, role=role))

        return RelevantContext(
            current_file=current_file,
            containing_symbol=_symbol(container) if container else None,
            files=files,
            snippets=selection.snippets,
            symbols=selection.symbols,
            relationships=relationships,
            diagnostics=list(diagnostics),
            metadata={
                "strategy": (
                    f"deterministic (symbols, imports, text) + semantic ({semantic['model']} embeddings)"
                    if semantic["used"]
                    else "deterministic (symbols, imports, text)"
                ),
                "semantic": semantic,
                "max_snippets": MAX_SNIPPETS,
                "max_chars": MAX_CONTEXT_CHARS,
                "chars": selection.chars,
                "truncated": selection.truncated,
                "used_unsaved_buffer": current_content is not None,
            },
        )

    @staticmethod
    def _semantic_query(
        diagnostics: Sequence[DiagnosticInput],
        query: str | None,
        current_symbol: str | None,
        container: CodeSymbol | None,
        lines: Sequence[str],
        line: int | None,
    ) -> str:
        """What the developer is looking at: diagnostics, query, and the code around the line."""
        parts = [d.message for d in diagnostics[:5]]
        parts += [t.strip() for t in (query, current_symbol) if t and t.strip()]
        if container is not None:
            parts.append("\n".join(lines[container.line - 1 : container.end_line]))
        elif line is not None:
            parts.append("\n".join(lines[max(0, line - 6) : line + 5]))
        return "\n".join(p for p in parts if p.strip())[:MAX_SEMANTIC_QUERY_CHARS]

    def _semantic(
        self,
        project: Project,
        index: ProjectIndex,
        selection: _Selection,
        *,
        current_file: str,
        text: str,
    ) -> dict[str, object]:
        retriever = self.search.retriever
        if retriever is None or not retriever.available:
            return {"used": False, "model": None, "detail": "semantic retrieval is not available"}
        if not text.strip():
            return {"used": False, "model": retriever.model, "detail": "nothing to search for"}
        if selection.full:
            return {"used": False, "model": retriever.model, "detail": "context limit reached"}
        try:
            hits = retriever.search(
                project, index, text, limit=SEMANTIC_CANDIDATES, exclude_path=current_file
            )
        except RetrievalError as exc:
            logger.warning("Semantic context unavailable: %s", exc.code)
            return {"used": False, "model": retriever.model, "detail": exc.message}
        added = 0
        for hit in hits:
            file = index.files.get(hit.file_path)
            if file is not None and selection.add_lines(
                file,
                hit.start_line,
                hit.end_line,
                f"semantically similar (cosine similarity {hit.similarity:.2f})",
            ):
                added += 1
        return {"used": added > 0, "model": retriever.model, "detail": None, "snippets": added}

    @staticmethod
    def _definitions(index: ProjectIndex, name: str, *, exclude: str) -> list[tuple[IndexedFile, CodeSymbol]]:
        return [
            (file, symbol)
            for file in index.files.values()
            if file.path != exclude
            for symbol in file.symbols
            if symbol.name == name
        ][:3]


class _Selection:
    def __init__(self) -> None:
        self.snippets: list[ContextSnippet] = []
        self.symbols: list[ContextSymbol] = []
        self.chars = 0
        self.truncated = False
        self._seen: set[tuple[str, int]] = set()

    def add_definition(self, file: IndexedFile, symbol: CodeSymbol, reason: str) -> None:
        if all(s.qualified_name != symbol.qualified_name or s.file_path != file.path for s in self.symbols):
            self.symbols.append(_symbol(symbol))
        self.add_lines(file, symbol.line, symbol.end_line, reason)

    @property
    def full(self) -> bool:
        return len(self.snippets) >= MAX_SNIPPETS or self.chars >= MAX_CONTEXT_CHARS

    def add_lines(self, file: IndexedFile, start: int, end: int, reason: str) -> bool:
        if (file.path, start) in self._seen:
            return False
        if len(self.snippets) >= MAX_SNIPPETS:
            self.truncated = True
            return False
        snippet = make_snippet(file, start, end, max_lines=MAX_DEFINITION_LINES)
        if snippet is None:
            return False
        size = sum(len(line) + 1 for line in snippet.lines)
        if self.chars + size > MAX_CONTEXT_CHARS:
            self.truncated = True
            return False
        self._seen.add((file.path, start))
        self.chars += size
        self.snippets.append(ContextSnippet(**snippet.model_dump(), reason=reason))
        return True
