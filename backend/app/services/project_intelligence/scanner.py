"""Secure recursive scanning of a project directory.

Security boundary: only paths inside ``root`` are read. Symbolic links and
junctions are never followed (they are reported as skipped), so a link cannot
lead the scanner outside the project. Secret files are never opened.

Ignore rules, in order: built-in dependency/generated directories, secret and
temporary files, then the project's own ``.gitignore`` files (nested ones apply
to their directory, as in Git).
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

from pathspec import GitIgnoreSpec

from app.services.project_intelligence.models import SourceFile

DEFAULT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        ".idea",
        ".vscode",
        ".next",
        "out",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".gradle",
        "target",
        ".turbo",
        ".parcel-cache",
    }
)

# Directories that are only ignored when they really are virtual environments,
# since "env" can be legitimate source.
VIRTUALENV_NAMES = frozenset({"env", "venv", ".venv"})

SECRET_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "*.kdbx",
)
SECRET_FILE_ALLOWLIST = frozenset({".env.example", ".env.sample", ".env.template"})
TEMPORARY_FILE_PATTERNS = ("*.tmp", "*.temp", "*.swp", "*.swo", "*~", ".DS_Store", "Thumbs.db", "desktop.ini")

BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class ScanOptions:
    ignored_directories: frozenset[str] = DEFAULT_IGNORED_DIRECTORIES
    extra_ignored_file_patterns: tuple[str, ...] = ()
    max_files: int = 10_000
    max_file_bytes: int = 2 * 1024 * 1024
    respect_gitignore: bool = True


@dataclass(frozen=True)
class SkippedEntry:
    path: str
    reason: str


@dataclass
class ScanResult:
    files: list[SourceFile] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)
    truncated: bool = False


def is_secret_file(name: str) -> bool:
    if name in SECRET_FILE_ALLOWLIST:
        return False
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_FILE_PATTERNS)


def is_temporary_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in TEMPORARY_FILE_PATTERNS)


def _is_virtualenv(path: Path) -> bool:
    return (path / "pyvenv.cfg").is_file()


def decode_text(data: bytes) -> str | None:
    """UTF-8 text, or None for binary / non-UTF-8 content."""
    if b"\x00" in data[:BINARY_SNIFF_BYTES]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# (base directory relative to the scan root, prefix to prepend, spec). Specs from
# directories above the scan root use a prefix; nested ones strip their base.
_Specs = tuple[tuple[str, str, GitIgnoreSpec], ...]


def _ancestor_specs(root: Path, boundary: Path | None) -> _Specs:
    """.gitignore files between ``boundary`` (inclusive) and ``root`` (exclusive)."""
    if boundary is None:
        return ()
    boundary = boundary.resolve()
    if root == boundary or not root.is_relative_to(boundary):
        return ()
    specs: list[tuple[str, str, GitIgnoreSpec]] = []
    current = root.parent
    while True:
        spec = _load_gitignore(current / ".gitignore")
        if spec is not None:
            specs.append(("", root.relative_to(current).as_posix() + "/", spec))
        if current == boundary:
            break
        current = current.parent
    return tuple(reversed(specs))


def scan_directory(
    root: Path, options: ScanOptions | None = None, *, gitignore_boundary: Path | None = None
) -> ScanResult:
    """Scan ``root``. ``gitignore_boundary`` (e.g. the workspace root) enables .gitignore
    files from the directories between it and ``root``, as Git would apply them."""
    options = options or ScanOptions()
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    result = ScanResult()
    initial = _ancestor_specs(root, gitignore_boundary) if options.respect_gitignore else ()
    pending: list[tuple[Path, str, _Specs]] = [(root, "", initial)]

    while pending:
        directory, relative_dir, inherited = pending.pop()
        specs = inherited
        if options.respect_gitignore:
            own = _load_gitignore(directory / ".gitignore")
            if own is not None:
                specs = (*inherited, (relative_dir, "", own))
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            result.skipped.append(SkippedEntry(relative_dir or ".", "unreadable directory"))
            continue
        subdirectories: list[tuple[Path, str, _Specs]] = []
        for entry in entries:
            relative = f"{relative_dir}/{entry.name}" if relative_dir else entry.name
            path = Path(entry.path)
            if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                result.skipped.append(SkippedEntry(relative, "symbolic link"))
                continue
            is_directory = entry.is_dir(follow_symlinks=False)
            if specs and _gitignored(specs, relative, is_directory):
                result.skipped.append(SkippedEntry(relative, "ignored by .gitignore"))
                continue
            if is_directory:
                if entry.name in options.ignored_directories and (
                    entry.name not in VIRTUALENV_NAMES or _is_virtualenv(path)
                ):
                    result.skipped.append(SkippedEntry(relative, "ignored directory"))
                elif _is_virtualenv(path):
                    result.skipped.append(SkippedEntry(relative, "virtual environment"))
                else:
                    result.directories.append(relative)
                    subdirectories.append((path, relative, specs))
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            skip_reason = _file_skip_reason(entry.name, options)
            if skip_reason:
                result.skipped.append(SkippedEntry(relative, skip_reason))
                continue
            if len(result.files) >= options.max_files:
                result.truncated = True
                result.skipped.append(SkippedEntry(relative, "file limit reached"))
                continue
            result.files.append(_read_file(path, relative, options))
        # Depth-first in name order.
        pending.extend(reversed(subdirectories))

    result.directories.sort()
    return result


def _load_gitignore(path: Path) -> GitIgnoreSpec | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        return GitIgnoreSpec.from_lines(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return None


def _gitignored(specs: _Specs, relative: str, is_directory: bool) -> bool:
    for base, prefix, spec in specs:
        local = prefix + (relative[len(base) + 1 :] if base else relative)
        if spec.match_file(local + "/" if is_directory else local):
            return True
    return False


def _file_skip_reason(name: str, options: ScanOptions) -> str | None:
    if is_secret_file(name):
        return "secret file"
    if is_temporary_file(name):
        return "temporary file"
    if any(fnmatch.fnmatch(name, pattern) for pattern in options.extra_ignored_file_patterns):
        return "ignored file"
    return None


def _read_file(path: Path, relative: str, options: ScanOptions) -> SourceFile:
    try:
        size = path.stat(follow_symlinks=False).st_size
        if size > options.max_file_bytes:
            return SourceFile(path=relative, size=size, content=None, skipped_reason="too large")
        with path.open("rb") as handle:
            data = handle.read(options.max_file_bytes + 1)
    except OSError:
        return SourceFile(path=relative, size=0, content=None, skipped_reason="unreadable")
    text = decode_text(data)
    if text is None:
        return SourceFile(path=relative, size=size, content=None, skipped_reason="binary or non-UTF-8")
    return SourceFile(path=relative, size=size, content=text)
