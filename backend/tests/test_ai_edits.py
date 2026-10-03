"""Safe code edits: conversion, validation, application, safety limits, diffs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.ai import CodeEdit
from app.services.ai.edits import (
    MAX_EDITS,
    InvalidEditError,
    apply_edits,
    check_change_is_safe,
    line_edits_to_code_edits,
    text_hash,
    unified_diff,
    validate_edits,
)
from app.services.ai.outputs import ModelLineEdit

CODE = "def total(items):\n    return sum(item.price for item in item)\n\nprint(total([]))\n"


def edit(start: int, end: int, replacement: str) -> ModelLineEdit:
    return ModelLineEdit(start_line=start, end_line=end, replacement=replacement)


def suggest(code: str, *edits: ModelLineEdit) -> str:
    code_edits = validate_edits("app.py", code, line_edits_to_code_edits("app.py", code, list(edits)))
    return apply_edits(code, code_edits)


def test_replace_insert_delete() -> None:
    fixed = suggest(CODE, edit(2, 2, "    return sum(item.price for item in items)"))
    assert fixed == CODE.replace("in item)", "in items)")
    inserted = suggest(CODE, edit(1, 1, "def total(items):\n    items = list(items)"))
    assert inserted.splitlines()[1] == "    items = list(items)"
    deleted = suggest(CODE, edit(3, 4, ""))
    assert deleted == "def total(items):\n    return sum(item.price for item in item)\n"


def test_multiple_edits_apply_in_document_order() -> None:
    fixed = suggest(CODE, edit(4, 4, "print(total([1]))"), edit(1, 1, "def total(items: list):"))
    assert fixed.startswith("def total(items: list):")
    assert fixed.endswith("print(total([1]))\n")


def test_line_endings_are_preserved() -> None:
    crlf = "a = 1\r\nb = 2\r\n"
    assert suggest(crlf, edit(2, 2, "b = 3\nc = 4")) == "a = 1\r\nb = 3\r\nc = 4\r\n"
    no_trailing = "a = 1\nb = 2"
    assert suggest(no_trailing, edit(2, 2, "b = 3")) == "a = 1\nb = 3"


@pytest.mark.parametrize(
    "bad",
    [edit(0, 1, "x"), edit(3, 2, "x"), edit(5, 5, "x"), edit(2, 99, "x")],
)
def test_out_of_range_line_edits_are_rejected(bad: ModelLineEdit) -> None:
    with pytest.raises(InvalidEditError):
        line_edits_to_code_edits("app.py", CODE, [bad])


def test_overlapping_edits_are_rejected() -> None:
    with pytest.raises(InvalidEditError, match="overlap"):
        suggest(CODE, edit(1, 2, "x"), edit(2, 3, "y"))


def code_edit(**overrides: object) -> CodeEdit:
    values: dict[str, object] = {
        "file_path": "app.py",
        "start_line": 1,
        "start_column": 1,
        "end_line": 1,
        "end_column": 4,
        "replacement_text": "async def",
    }
    values.update(overrides)
    return CodeEdit.model_validate(values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"file_path": "other.py"}, "only change the file"),
        ({"start_line": 9, "end_line": 9}, "outside the file"),
        ({"end_column": 200}, "outside line"),
        ({"start_line": 2, "end_line": 1}, "ends before"),
    ],
)
def test_invalid_code_edits(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidEditError, match=message):
        validate_edits("app.py", CODE, [code_edit(**overrides)])


@pytest.mark.parametrize("path", ["../secrets.py", "/etc/passwd", "C:/Windows/x.py", "a/../../b.py", ".env"])
def test_edit_paths_cannot_escape_the_project(path: str) -> None:
    with pytest.raises(ValidationError):
        code_edit(file_path=path)


def test_too_many_edits() -> None:
    edits = [code_edit(start_line=1, end_line=1, start_column=1, end_column=1)] * (MAX_EDITS + 1)
    with pytest.raises(InvalidEditError, match="at most"):
        validate_edits("app.py", CODE, edits)


def test_disproportionate_changes_are_rejected() -> None:
    with pytest.raises(InvalidEditError, match="whole file"):
        check_change_is_safe(CODE, "   \n")
    big = "\n".join(f"x{i} = {i}" for i in range(500))
    with pytest.raises(InvalidEditError, match="more than"):
        check_change_is_safe(big, big.replace("= ", "== "))
    check_change_is_safe(CODE, CODE.replace("item)", "items)"))  # a targeted fix passes


def test_unified_diff_and_hash() -> None:
    fixed = CODE.replace("in item)", "in items)")
    diff = unified_diff("app.py", CODE, fixed)
    assert diff.startswith("--- a/app.py\n+++ b/app.py\n")
    assert "-    return sum(item.price for item in item)\n" in diff
    assert "+    return sum(item.price for item in items)\n" in diff
    assert unified_diff("app.py", CODE, CODE) == ""
    assert text_hash(CODE) != text_hash(fixed)
    assert len(text_hash(CODE)) == 64
