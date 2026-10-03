"""Safe path handling for user-supplied relative paths.

Any feature that maps client-provided paths onto the filesystem (project
files, uploads) must go through ``resolve_within`` so that traversal such as
``../../etc/passwd``, absolute paths, drive letters, or symlink escapes are
rejected.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from app.core.exceptions import UnsafePathError

MAX_RELATIVE_PATH_LENGTH = 1024


def normalize_relative_path(raw: str) -> PurePosixPath:
    """Validate a client-supplied relative path and return it in POSIX form.

    Rejects empty paths, absolute paths, drive/UNC prefixes, ``..`` segments,
    NUL bytes, and overly long input. ``.`` segments and duplicate separators
    are collapsed.
    """
    if not raw or len(raw) > MAX_RELATIVE_PATH_LENGTH:
        raise UnsafePathError("Path is empty or too long.")
    if "\x00" in raw:
        raise UnsafePathError("Path contains invalid characters.")

    unified = raw.replace("\\", "/")
    windows_view = PureWindowsPath(raw)
    if unified.startswith("/") or windows_view.drive or windows_view.root:
        raise UnsafePathError("Absolute paths are not allowed.")

    parts = [part for part in unified.split("/") if part not in ("", ".")]
    if not parts:
        raise UnsafePathError("Path is empty.")
    if any(part == ".." for part in parts):
        raise UnsafePathError("Parent directory references are not allowed.")
    return PurePosixPath(*parts)


def resolve_within(root: Path, raw_relative: str) -> Path:
    """Resolve ``raw_relative`` under ``root`` and guarantee it stays inside.

    Symlinks are resolved before the containment check, so a link pointing
    outside ``root`` is rejected as well.
    """
    relative = normalize_relative_path(raw_relative)
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise UnsafePathError("Path escapes the project root.")
    return candidate
