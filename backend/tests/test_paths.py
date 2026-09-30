from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.exceptions import UnsafePathError
from app.utils.paths import normalize_relative_path, resolve_within


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src/main.py", "src/main.py"),
        ("src\\pkg\\mod.py", "src/pkg/mod.py"),
        ("./src//main.py", "src/main.py"),
    ],
)
def test_normalizes_safe_paths(raw: str, expected: str) -> None:
    assert normalize_relative_path(raw).as_posix() == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        ".",
        "../secrets.txt",
        "src/../../etc/passwd",
        "..\\..\\windows\\system32",
        "/etc/passwd",
        "\\server\\share",
        "C:\\Windows",
        "C:relative",
        "file\x00.py",
        "a/" * 600,
    ],
)
def test_rejects_unsafe_paths(raw: str) -> None:
    with pytest.raises(UnsafePathError):
        normalize_relative_path(raw)


def test_resolve_within_stays_inside_root(tmp_path: Path) -> None:
    resolved = resolve_within(tmp_path, "pkg/module.py")
    assert resolved == (tmp_path / "pkg" / "module.py").resolve()


def test_resolve_within_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        os.symlink(outside, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires extra privileges on this platform")

    with pytest.raises(UnsafePathError):
        resolve_within(root, "link/data.txt")
