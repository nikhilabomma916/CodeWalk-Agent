"""Programming language detection from file extensions.

Extension table mirrors docs/PRD.md section 11.5 / docs/project-intelligence.md
section 7, so language names stay consistent across the whole project.
"""

from __future__ import annotations

import os
from typing import Optional

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".go": "go",
    ".rs": "rust",
}

# Directories the eventual project-level scanner should skip; kept here so
# the mapping/ignore rules for "what counts as source" live in one place.
IGNORED_DIRECTORIES: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        "dist",
        "build",
        ".venv",
        "venv",
        "coverage",
    }
)


def detect_language(file_path: str) -> Optional[str]:
    """Return the detected language for a file path, or None if unknown."""

    _, ext = os.path.splitext(file_path)
    return EXTENSION_LANGUAGE_MAP.get(ext.lower())


def is_supported(language: str) -> bool:
    """Whether the analysis engine currently has an analyzer for this language."""

    from code_analysis.analyzers import get_analyzer

    return get_analyzer(language) is not None
