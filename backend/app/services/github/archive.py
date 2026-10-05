"""Read a GitHub repository archive (``.tar.gz``) into text files, safely and within limits.

Nothing is written to disk and only regular files are read, so symbolic links, hard links, devices
and ``..`` paths cannot reach anything outside the archive. Every path is checked again by the
regular file import (``FileService.import_files``) before it is stored.

Skipped without being read: links and special files, dependency/build folders, credentials files
(``.env``, keys), and files over the per-file limit. Read and then skipped: binary files (a NUL byte,
or not UTF-8). The whole archive is refused (nothing is imported) when it is larger than the
repository limit, declares more data than that in total, or holds too many entries.
"""

from __future__ import annotations

import io
import tarfile
import time
from dataclasses import dataclass, field

from app.services.project_intelligence.scanner import DEFAULT_IGNORED_DIRECTORIES, is_secret_path

BINARY_SNIFF_BYTES = 8000


class ArchiveTooLargeError(Exception):
    pass


class ArchiveInvalidError(Exception):
    pass


class ArchiveTimeoutError(Exception):
    pass


@dataclass
class ArchiveContents:
    files: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    text_bytes: int = 0


def read_archive(
    data: bytes,
    *,
    max_file_bytes: int,
    max_files: int,
    max_total_bytes: int,
    deadline: float,
) -> ArchiveContents:
    contents = ArchiveContents()
    declared = 0
    entries = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive:
                entries += 1
                if entries > max_files * 4 + 1000:
                    raise ArchiveTooLargeError("The repository has too many entries.")
                if time.monotonic() > deadline:
                    raise ArchiveTimeoutError()
                path = _relative(member.name)
                if path is None or member.isdir():
                    continue
                if member.issym() or member.islnk():
                    contents.skipped.append((path, "symlink"))
                    continue
                if not member.isfile():
                    contents.skipped.append((path, "special_file"))
                    continue
                declared += member.size
                if declared > max_total_bytes * 4:
                    raise ArchiveTooLargeError("The repository is larger than the import limit.")
                folders = path.split("/")[:-1]
                if any(folder in DEFAULT_IGNORED_DIRECTORIES for folder in folders):
                    contents.skipped.append((path, "ignored"))
                elif is_secret_path(path):
                    contents.skipped.append((path, "secret"))
                elif member.size > max_file_bytes:
                    contents.skipped.append((path, "too_large"))
                elif len(contents.files) >= max_files:
                    contents.skipped.append((path, "limit"))
                else:
                    reader = archive.extractfile(member)
                    raw = reader.read(max_file_bytes + 1) if reader is not None else b""
                    text = _text(raw)
                    if text is None:
                        contents.skipped.append((path, "binary"))
                        continue
                    contents.text_bytes += len(raw)
                    if contents.text_bytes > max_total_bytes:
                        raise ArchiveTooLargeError("The repository is larger than the import limit.")
                    contents.files.append((path, text))
    except (tarfile.TarError, EOFError, OSError, ValueError):
        raise ArchiveInvalidError() from None
    return contents


def _relative(name: str) -> str | None:
    """Drop GitHub's top folder (``owner-repo-sha/``); None for the folder itself or odd names."""
    parts = name.replace("\\", "/").split("/", 1)
    if len(parts) != 2 or not parts[1].strip("/"):
        return None
    return parts[1].strip("/")


def _text(raw: bytes) -> str | None:
    if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
