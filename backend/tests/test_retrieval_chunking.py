"""Chunking of indexed files and reciprocal rank fusion."""

from __future__ import annotations

from app.services.languages import Language
from app.services.project_intelligence.models import SourceFile
from app.services.project_intelligence.project_analyzer import STRUCTURE_LANGUAGES, extract_structure
from app.services.project_search.index import IndexedFile
from app.services.retrieval import fusion
from app.services.retrieval.chunking import (
    MAX_CHUNK_CHARS,
    MAX_CHUNK_LINES,
    MAX_CHUNKS_PER_FILE,
    WINDOW_LINES,
    chunk_file,
)

SERVICE = '''import hashlib
from db import connect


class UserService:
    """Users."""

    def __init__(self, repo):
        self.repo = repo

    def authenticate_user(self, email, password):
        user = self.repo.find(email)
        return user is not None and user.check(password)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


DEFAULT_ROUNDS = 3
'''


def indexed(path: str, content: str, language: Language = Language.PYTHON) -> IndexedFile:
    symbols = []
    if language in STRUCTURE_LANGUAGES:
        source = SourceFile(path=path, size=len(content), content=content)
        symbols = list(extract_structure(source, language).symbols)
    return IndexedFile(
        path=path,
        name=path.rsplit("/", 1)[-1],
        language=language,
        lines=content.splitlines(),
        symbols=symbols,
    )


def test_chunks_follow_symbols_and_cover_the_rest() -> None:
    chunks = chunk_file(indexed("src/auth/service.py", SERVICE))
    spans = [(c.start_line, c.end_line, c.symbol_name, c.symbol_kind) for c in chunks]
    assert spans == [
        (1, 4, None, None),  # imports (and the blank lines after them)
        (5, 7, "UserService", "class"),  # class header, up to its first method
        (8, 9, "UserService.__init__", "method"),
        (11, 13, "UserService.authenticate_user", "method"),
        (16, 17, "hash_password", "function"),  # blank-only gaps (line 10, lines 14-15) are skipped
        (18, 20, None, None),  # module-level code
    ]
    assert [c.index for c in chunks] == list(range(len(chunks)))
    method = next(c for c in chunks if c.symbol_name == "UserService.authenticate_user")
    assert method.text.startswith("File: src/auth/service.py\nmethod UserService.authenticate_user\n")
    assert "user.check(password)" in method.text
    # Every non-blank line belongs to exactly one chunk.
    lines = SERVICE.splitlines()
    covered = [n for c in chunks for n in range(c.start_line, c.end_line + 1)]
    assert len(covered) == len(set(covered))
    assert {n for n, text in enumerate(lines, start=1) if text.strip()} <= set(covered)


def test_long_symbols_and_plain_files_are_split() -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(150))
    chunks = chunk_file(indexed("big.py", f"def big():\n{body}\n"))
    assert [c.symbol_name for c in chunks] == ["big", "big", "big"]
    assert all(c.end_line - c.start_line + 1 <= MAX_CHUNK_LINES for c in chunks)
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 151

    notes = "\n".join(f"line {i}" for i in range(100))
    plain = chunk_file(indexed("docs/notes.md", notes, Language.MARKDOWN))
    assert [(c.start_line, c.end_line) for c in plain] == [(1, 40), (41, 80), (81, 100)]
    assert all(c.symbol_name is None for c in plain)
    assert WINDOW_LINES == 40


def test_limits_and_empty_files() -> None:
    assert chunk_file(indexed("empty.py", "")) == []
    assert chunk_file(indexed("blank.py", "\n\n   \n")) == []
    assert (
        chunk_file(IndexedFile(path="bin.dat", name="bin.dat", language=Language.PLAINTEXT, lines=None)) == []
    )

    wide = chunk_file(indexed("wide.py", "x = '" + "a" * 20_000 + "'\n"))
    assert len(wide) == 1
    assert len(wide[0].text) == MAX_CHUNK_CHARS

    many = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(400))
    assert len(chunk_file(indexed("many.py", many))) == MAX_CHUNKS_PER_FILE


def test_chunk_hash_covers_text_and_location() -> None:
    first = chunk_file(indexed("a/service.py", SERVICE))
    again = chunk_file(indexed("a/service.py", SERVICE))
    moved = chunk_file(indexed("b/service.py", SERVICE))
    assert [c.hash for c in first] == [c.hash for c in again]
    assert {c.hash for c in first}.isdisjoint(c.hash for c in moved)

    edited = chunk_file(indexed("a/service.py", SERVICE.replace("hexdigest()", "digest()")))
    changed = {c.symbol_name for c in edited if c.hash not in {f.hash for f in first}}
    assert changed == {"hash_password"}


# --- reciprocal rank fusion ----------------------------------------------------------------


def test_rrf_scores_and_order() -> None:
    fused = fusion.rrf(["a", "b", "c"], ["c", "d"])
    scores = {f.key: f.score for f in fused}
    k = fusion.K
    assert scores["a"] == 1 / (k + 1)
    assert scores["c"] == 1 / (k + 3) + 1 / (k + 1)
    assert scores["d"] == 1 / (k + 2)
    assert [f.key for f in fused] == ["c", "a", "b", "d"]
    c = next(f for f in fused if f.key == "c")
    assert (c.deterministic_rank, c.semantic_rank) == (3, 1)


def test_rrf_ties_prefer_the_deterministic_rank() -> None:
    fused = fusion.rrf(["x"], ["y"])
    assert [f.key for f in fused] == ["x", "y"]
    assert fused[0].score == fused[1].score
    assert fusion.rrf([], []) == []
    duplicate = fusion.rrf(["a", "a"], [])
    assert [(f.key, f.deterministic_rank) for f in duplicate] == [("a", 1)]
