"""Manual demo/validation tool for the analysis engine.

Usage:
    python -m code_analysis.cli path/to/file.py
"""

from __future__ import annotations

import sys

from code_analysis.engine import UnsupportedLanguageError, analyze_code


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python -m code_analysis.cli <file>", file=sys.stderr)
        return 2

    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        print(f"Could not read {path}: {exc}", file=sys.stderr)
        return 1

    try:
        result = analyze_code(source=source, file_path=path)
    except UnsupportedLanguageError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    print(f"{result.file_path} [{result.language}]")
    print(
        f"  {result.error_count} error(s), {result.warning_count} warning(s), "
        f"{result.suggestion_count} suggestion(s)"
    )
    for d in result.diagnostics:
        col = f":{d.column}" if d.column is not None else ""
        print(f"  {d.severity.value:>10} {d.line}{col}  [{d.source}/{d.code}] {d.message}")

    return 1 if result.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
