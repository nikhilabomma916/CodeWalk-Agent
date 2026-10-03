"""Deterministic language detection shared by code analysis and project intelligence.

Detection is by file name/extension only. Anything not listed is ``Language.UNKNOWN``;
we never guess from content.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath


class Language(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    JAVASCRIPT_REACT = "javascriptreact"
    TYPESCRIPT = "typescript"
    TYPESCRIPT_REACT = "typescriptreact"
    JSON = "json"
    HTML = "html"
    CSS = "css"
    SQL = "sql"
    MARKDOWN = "markdown"
    JAVA = "java"
    C = "c"
    CPP = "cpp"
    # Recognized for statistics; no analyzer yet.
    SCSS = "scss"
    YAML = "yaml"
    TOML = "toml"
    XML = "xml"
    SHELL = "shell"
    GO = "go"
    RUST = "rust"
    CSHARP = "csharp"
    PHP = "php"
    RUBY = "ruby"
    KOTLIN = "kotlin"
    SWIFT = "swift"
    DOCKERFILE = "dockerfile"
    PLAINTEXT = "plaintext"
    UNKNOWN = "unknown"


_BY_EXTENSION: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT_REACT,
    ".ts": Language.TYPESCRIPT,
    ".mts": Language.TYPESCRIPT,
    ".cts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT_REACT,
    ".json": Language.JSON,
    ".jsonc": Language.JSON,
    ".html": Language.HTML,
    ".htm": Language.HTML,
    ".css": Language.CSS,
    ".sql": Language.SQL,
    ".md": Language.MARKDOWN,
    ".markdown": Language.MARKDOWN,
    ".java": Language.JAVA,
    ".c": Language.C,
    ".h": Language.C,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".hpp": Language.CPP,
    ".hh": Language.CPP,
    ".hxx": Language.CPP,
    ".scss": Language.SCSS,
    ".yml": Language.YAML,
    ".yaml": Language.YAML,
    ".toml": Language.TOML,
    ".xml": Language.XML,
    ".svg": Language.XML,
    ".sh": Language.SHELL,
    ".bash": Language.SHELL,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".cs": Language.CSHARP,
    ".php": Language.PHP,
    ".rb": Language.RUBY,
    ".kt": Language.KOTLIN,
    ".swift": Language.SWIFT,
    ".txt": Language.PLAINTEXT,
}

_BY_NAME: dict[str, Language] = {
    "dockerfile": Language.DOCKERFILE,
}

# JSON files whose tooling accepts comments and trailing commas.
_JSONC_NAMES = ("tsconfig", "jsconfig", ".eslintrc", "devcontainer")


def detect_language(path: str) -> Language:
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    if name in _BY_NAME:
        return _BY_NAME[name]
    if name.startswith("dockerfile."):
        return Language.DOCKERFILE
    suffix = PurePosixPath(name).suffix
    return _BY_EXTENSION.get(suffix, Language.UNKNOWN)


def is_jsonc(path: str | None) -> bool:
    """JSON-with-comments files (tsconfig.json, .jsonc, VS Code settings, ...)."""
    if not path:
        return False
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    return name.endswith(".jsonc") or any(name.startswith(prefix) for prefix in _JSONC_NAMES)
