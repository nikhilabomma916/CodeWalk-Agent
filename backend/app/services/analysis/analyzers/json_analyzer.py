"""JSON analysis using Python's standard-library parser.

Reports the exact position of the first syntax error and warns about duplicate
object keys. JSON-with-comments files (tsconfig.json, *.jsonc) are accepted with
comments and trailing commas, as their tooling allows.
"""

from __future__ import annotations

import json
import platform
from typing import Any

from app.services.analysis.analyzers.base import AnalysisContext, AnalyzerOutput, make_diagnostic
from app.services.analysis.models import (
    AnalyzerInfo,
    Capability,
    CapabilityKind,
    CapabilityStatus,
    Diagnostic,
    DiagnosticCategory,
    Severity,
)
from app.services.languages import Language, is_jsonc

SOURCE = "json"


def strip_jsonc(text: str) -> str:
    """Blank out comments and trailing commas while preserving every offset."""
    chars = list(text)
    i, length = 0, len(text)
    in_string = False
    last_significant: int | None = None  # index of the last non-space char outside comments
    while i < length:
        char = text[i]
        if in_string:
            if char == "\\":
                i += 2
                continue
            if char == '"':
                in_string = False
                last_significant = i
            i += 1
            continue
        if char == '"':
            in_string = True
        elif text.startswith("//", i):
            while i < length and text[i] != "\n":
                chars[i] = " "
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = length if end == -1 else end + 2
            for j in range(i, end):
                if text[j] != "\n":
                    chars[j] = " "
            i = end
            continue
        elif char in "}]" and last_significant is not None and chars[last_significant] == ",":
            chars[last_significant] = " "
        if not char.isspace():
            last_significant = i
        i += 1
    return "".join(chars)


class _DuplicateKeyCollector:
    def __init__(self) -> None:
        self.duplicates: list[str] = []

    def __call__(self, pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                self.duplicates.append(key)
            seen[key] = value
        return seen


class JsonAnalyzer:
    name = "json"
    languages = frozenset({Language.JSON})

    def info(self) -> list[AnalyzerInfo]:
        return [AnalyzerInfo(name="python-json", version=platform.python_version())]

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        text = context.source
        lenient = is_jsonc(context.file_path)
        if lenient:
            text = strip_jsonc(text)
        diagnostics: list[Diagnostic] = []
        capabilities = [
            Capability(
                kind=CapabilityKind.SYNTAX,
                status=CapabilityStatus.PERFORMED,
                analyzer="python-json",
                detail="JSON with comments" if lenient else "strict JSON (RFC 8259)",
            ),
            Capability(
                kind=CapabilityKind.LINT,
                status=CapabilityStatus.PERFORMED,
                analyzer="python-json",
                detail="duplicate keys",
            ),
            Capability(
                kind=CapabilityKind.TYPES,
                status=CapabilityStatus.NOT_SUPPORTED,
                detail="JSON Schema validation is not implemented",
            ),
        ]
        if not text.strip():
            if not lenient:
                diagnostics.append(
                    make_diagnostic(
                        context=context,
                        severity=Severity.ERROR,
                        message="Empty JSON document",
                        source=SOURCE,
                        category=DiagnosticCategory.SYNTAX,
                        line=1,
                        column=1,
                    )
                )
            return AnalyzerOutput(diagnostics=diagnostics, capabilities=capabilities)

        collector = _DuplicateKeyCollector()
        try:
            json.loads(text, object_pairs_hook=collector)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                make_diagnostic(
                    context=context,
                    severity=Severity.ERROR,
                    message=f"Invalid JSON: {exc.msg}",
                    source=SOURCE,
                    category=DiagnosticCategory.SYNTAX,
                    line=exc.lineno,
                    column=exc.colno,
                )
            )
            return AnalyzerOutput(diagnostics=diagnostics, capabilities=capabilities)

        for key in dict.fromkeys(collector.duplicates):
            line, column = _locate_key(context.source, key)
            diagnostics.append(
                make_diagnostic(
                    context=context,
                    severity=Severity.WARNING,
                    message=f'Duplicate key "{key}"; only the last value is kept',
                    source=SOURCE,
                    category=DiagnosticCategory.LINT,
                    code="duplicate-key",
                    line=line,
                    column=column,
                    end_column=column + len(key) + 2,
                )
            )
        return AnalyzerOutput(diagnostics=diagnostics, capabilities=capabilities)


def _locate_key(source: str, key: str) -> tuple[int, int]:
    """Position of the last occurrence of a quoted key (the duplicate)."""
    needle = json.dumps(key)
    offset = source.rfind(needle)
    if offset == -1:
        return 1, 1
    line = source.count("\n", 0, offset) + 1
    column = offset - (source.rfind("\n", 0, offset) + 1) + 1
    return line, column
