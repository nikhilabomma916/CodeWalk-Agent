"""Split an indexed project file into chunks for embedding.

Chunks follow the Module 5 structure already held by the Module 9 index (no
re-parsing): each function, method, class, interface, enum, or type alias is one
chunk; a class with methods contributes its header (the lines before its first
member) and each member separately. Lines outside every symbol (imports,
module-level code, files without structure support) are grouped into fixed
windows; blank-only windows are skipped. Long ranges are split, and every chunk
is bounded in lines and characters.

The embedded text starts with the file path and the symbol, so a chunk carries
where it lives; ``hash`` covers exactly that text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.services.project_intelligence.models import CodeSymbol, SymbolKind
from app.services.project_search.index import IndexedFile

CHUNK_KINDS = frozenset(
    {
        SymbolKind.FUNCTION,
        SymbolKind.METHOD,
        SymbolKind.CLASS,
        SymbolKind.INTERFACE,
        SymbolKind.ENUM,
        SymbolKind.TYPE_ALIAS,
    }
)
MAX_CHUNK_LINES = 60
WINDOW_LINES = 40
MAX_CHUNK_CHARS = 4000
MAX_CHUNKS_PER_FILE = 200


@dataclass(frozen=True)
class Chunk:
    index: int
    start_line: int
    end_line: int
    symbol_name: str | None
    symbol_kind: str | None
    text: str
    hash: str


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    symbol: CodeSymbol | None


def _symbol_units(symbols: list[CodeSymbol], line_count: int) -> list[_Unit]:
    chunkable = [s for s in symbols if s.kind in CHUNK_KINDS and 1 <= s.line <= line_count]
    children: dict[str, list[CodeSymbol]] = {}
    for symbol in chunkable:
        if symbol.parent is not None:
            children.setdefault(symbol.parent, []).append(symbol)
    units: list[_Unit] = []
    for symbol in chunkable:
        end = min(max(symbol.end_line, symbol.line), line_count)
        members = children.get(symbol.id)
        if members:
            first = min(m.line for m in members)
            if first > symbol.line:
                units.append(_Unit(symbol.line, min(first - 1, end), symbol))
        else:
            units.append(_Unit(symbol.line, end, symbol))
    return units


def _split(unit: _Unit, size: int) -> list[_Unit]:
    return [
        _Unit(start, min(start + size - 1, unit.end), unit.symbol)
        for start in range(unit.start, unit.end + 1, size)
    ]


def chunk_file(file: IndexedFile) -> list[Chunk]:
    """Chunks of a stored file in line order (empty for files without stored content)."""
    lines = file.lines
    if not lines or not any(line.strip() for line in lines):
        return []
    units = _symbol_units(file.symbols, len(lines))

    covered = [False] * (len(lines) + 1)
    for unit in units:
        for number in range(unit.start, unit.end + 1):
            covered[number] = True
    gap_start: int | None = None
    for number in range(1, len(lines) + 2):
        inside = number <= len(lines) and not covered[number]
        if inside and gap_start is None:
            gap_start = number
        elif not inside and gap_start is not None:
            units.extend(_split(_Unit(gap_start, number - 1, None), WINDOW_LINES))
            gap_start = None

    parts = [part for unit in units for part in _split(unit, MAX_CHUNK_LINES)]
    parts = [p for p in parts if any(line.strip() for line in lines[p.start - 1 : p.end])]
    parts.sort(key=lambda p: (p.start, p.end))

    chunks: list[Chunk] = []
    for index, part in enumerate(parts[:MAX_CHUNKS_PER_FILE]):
        symbol = part.symbol
        header = f"File: {file.path}\n"
        if symbol is not None:
            header += f"{symbol.kind.value} {symbol.qualified_name}\n"
        text = (header + "\n".join(lines[part.start - 1 : part.end]))[:MAX_CHUNK_CHARS]
        chunks.append(
            Chunk(
                index=index,
                start_line=part.start,
                end_line=part.end,
                symbol_name=symbol.qualified_name if symbol else None,
                symbol_kind=symbol.kind.value if symbol else None,
                text=text,
                hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return chunks
