"""Safe code edits: validation, application to a known text, and unified diffs.

Edits are only ever applied to a string the caller supplied (the code a fix was
computed against) to produce a *proposal*. Nothing here writes files: the
developer reviews the proposal and applies it in the editor, then saves.
"""

from __future__ import annotations

import difflib
import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.exceptions import AppError
from app.schemas.ai import CodeEdit
from app.services.ai.outputs import ModelLineEdit

MAX_EDITS = 20
MAX_REPLACEMENT_CHARS = 100_000
MAX_CHANGED_LINES = 400


class InvalidEditError(AppError):
    status_code = 422
    code = "invalid_edit"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


@dataclass(frozen=True)
class _Lines:
    """Line table of a text: start offsets and content lengths (without line endings)."""

    starts: list[int]
    lengths: list[int]

    @classmethod
    def of(cls, text: str) -> _Lines:
        starts: list[int] = []
        lengths: list[int] = []
        offset = 0
        for line in text.splitlines(keepends=True):
            starts.append(offset)
            lengths.append(len(line.rstrip("\r\n")))
            offset += len(line)
        if not starts or text.endswith(("\n", "\r")):
            starts.append(offset)  # the (empty) line after a trailing newline
            lengths.append(0)
        return cls(starts, lengths)

    @property
    def count(self) -> int:
        return len(self.starts)

    def offset(self, line: int, column: int) -> int:
        return self.starts[line - 1] + column - 1


def line_table(text: str) -> _Lines:
    """Line start offsets of ``text``; ``.offset(line, column)`` maps a 1-based position to an index."""
    return _Lines.of(text)


def line_edits_to_code_edits(file_path: str, code: str, edits: Sequence[ModelLineEdit]) -> list[CodeEdit]:
    """Turn whole-line replacements (as the model returns them) into exact ranges.

    Lines start_line..end_line are replaced including their line break, so an
    empty replacement deletes the lines and a replacement may add lines.
    """
    lines = _Lines.of(code)
    # A trailing newline produces an empty final entry in the line table that is not a real line.
    real_lines = lines.count - (1 if code.endswith(("\n", "\r")) else 0)
    newline = newline_of(code)
    result: list[CodeEdit] = []
    for edit in edits:
        if edit.start_line < 1 or edit.end_line < edit.start_line or edit.end_line > real_lines:
            raise InvalidEditError(
                f"Edit lines {edit.start_line}-{edit.end_line} are outside the file (1-{real_lines})."
            )
        replacement = edit.replacement.replace("\r\n", "\n").replace("\n", newline)
        if edit.end_line < lines.count:
            # Replace up to the start of the next line, taking the line break with it.
            end_line, end_column = edit.end_line + 1, 1
            if replacement:
                replacement += newline
        else:  # last line of a file without a trailing newline
            end_line, end_column = edit.end_line, lines.lengths[edit.end_line - 1] + 1
        result.append(
            CodeEdit(
                file_path=file_path,
                start_line=edit.start_line,
                start_column=1,
                end_line=end_line,
                end_column=end_column,
                replacement_text=replacement,
            )
        )
    return result


def validate_edits(target_path: str, code: str, edits: Sequence[CodeEdit]) -> list[CodeEdit]:
    """Check every edit against the target file and the text; return them in document order."""
    if len(edits) > MAX_EDITS:
        raise InvalidEditError(f"A suggestion may contain at most {MAX_EDITS} edits.")
    lines = _Lines.of(code)
    for edit in edits:
        if edit.file_path != target_path:
            raise InvalidEditError("Edits may only change the file the suggestion is for.")
        for line, column in ((edit.start_line, edit.start_column), (edit.end_line, edit.end_column)):
            if line > lines.count:
                raise InvalidEditError(f"Line {line} is outside the file ({lines.count} lines).")
            if column > lines.lengths[line - 1] + 1:
                raise InvalidEditError(f"Column {column} is outside line {line}.")
        if (edit.end_line, edit.end_column) < (edit.start_line, edit.start_column):
            raise InvalidEditError("An edit ends before it starts.")
        if len(edit.replacement_text) > MAX_REPLACEMENT_CHARS:
            raise InvalidEditError("An edit's replacement text is too large.")
    ordered = sorted(edits, key=lambda e: (e.start_line, e.start_column))
    for previous, current in itertools.pairwise(ordered):
        if (current.start_line, current.start_column) < (previous.end_line, previous.end_column):
            raise InvalidEditError("Edits overlap.")
    return ordered


def apply_edits(code: str, edits: Sequence[CodeEdit]) -> str:
    """Apply validated edits (any order) to ``code`` and return the new text."""
    lines = _Lines.of(code)
    result = code
    for edit in sorted(edits, key=lambda e: (e.start_line, e.start_column), reverse=True):
        start = lines.offset(edit.start_line, edit.start_column)
        end = lines.offset(edit.end_line, edit.end_column)
        result = result[:start] + edit.replacement_text + result[end:]
    return result


def check_change_is_safe(original: str, suggested: str) -> None:
    """Reject proposals that are disproportionate to a targeted fix."""
    if original.strip() and not suggested.strip():
        raise InvalidEditError("The suggestion would delete the whole file.")
    changed = sum(
        1 for line in difflib.ndiff(original.splitlines(), suggested.splitlines()) if line[:1] in "+-"
    )
    if changed > MAX_CHANGED_LINES:
        raise InvalidEditError(f"The suggestion changes more than {MAX_CHANGED_LINES} lines.")


def unified_diff(path: str, original: str, suggested: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            suggested.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
