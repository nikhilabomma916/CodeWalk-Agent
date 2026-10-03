"""JavaScript and TypeScript analysis with the TypeScript compiler.

- TypeScript/TSX: syntax errors, type errors (strict null checks; implicit ``any``
  allowed), unused and unreachable code.
- JavaScript/JSX: syntax errors, redeclarations, assignments to constants, unused
  and unreachable code. JavaScript is not type-checked, to avoid false positives
  on dynamic code.

Imports are not resolved (the rest of the project is not loaded), so errors that
only mean "module not found" are suppressed.
"""

from __future__ import annotations

from typing import Any

from app.services.analysis.analyzers.base import AnalysisContext, AnalyzerOutput, make_diagnostic
from app.services.analysis.models import (
    AnalyzerInfo,
    Capability,
    CapabilityKind,
    CapabilityStatus,
    DiagnosticCategory,
    Severity,
)
from app.services.analysis.typescript_worker import TypeScriptWorker, TypeScriptWorkerError
from app.services.languages import Language

SOURCE = "typescript"

_EXTENSIONS = {
    Language.TYPESCRIPT: ".ts",
    Language.TYPESCRIPT_REACT: ".tsx",
    Language.JAVASCRIPT: ".js",
    Language.JAVASCRIPT_REACT: ".jsx",
}
_CATEGORIES = {
    "syntax": DiagnosticCategory.SYNTAX,
    "type": DiagnosticCategory.TYPE,
    "semantic": DiagnosticCategory.SEMANTIC,
    "suggestion": DiagnosticCategory.LINT,
}
_SEVERITIES = {
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "information": Severity.INFORMATION,
}


class TypeScriptAnalyzer:
    name = "typescript"
    languages = frozenset(_EXTENSIONS)

    def __init__(self, worker: TypeScriptWorker) -> None:
        self._worker = worker

    def info(self) -> list[AnalyzerInfo]:
        return [AnalyzerInfo(name=SOURCE, version=self._worker.version)]

    def unavailable_reason(self) -> str | None:
        return self._worker.unavailable_reason()

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        is_typescript = context.language in (Language.TYPESCRIPT, Language.TYPESCRIPT_REACT)
        output = AnalyzerOutput()
        try:
            items = self._worker.analyze(
                f"input{_EXTENSIONS[context.language]}", context.source, context.timeout_seconds
            )
        except TypeScriptWorkerError as exc:
            output.errors.append(str(exc))
            for kind in (
                CapabilityKind.SYNTAX,
                CapabilityKind.TYPES if is_typescript else CapabilityKind.SEMANTIC,
            ):
                output.capabilities.append(
                    Capability(
                        kind=kind, status=CapabilityStatus.UNAVAILABLE, analyzer=SOURCE, detail=str(exc)
                    )
                )
            return output

        has_syntax_errors = any(item.get("category") == "syntax" for item in items)
        output.capabilities = [
            Capability(kind=CapabilityKind.SYNTAX, status=CapabilityStatus.PERFORMED, analyzer=SOURCE),
            Capability(
                kind=CapabilityKind.TYPES if is_typescript else CapabilityKind.SEMANTIC,
                status=CapabilityStatus.SKIPPED if has_syntax_errors else CapabilityStatus.PERFORMED,
                analyzer=SOURCE,
                detail=(
                    "Fix syntax errors to enable type checking"
                    if has_syntax_errors
                    else "Single file; imports are not resolved"
                    if is_typescript
                    else "Redeclarations, constant assignment, unused and unreachable code; no type checking"
                ),
            ),
        ]
        if not is_typescript:
            output.capabilities.append(
                Capability(
                    kind=CapabilityKind.TYPES,
                    status=CapabilityStatus.NOT_SUPPORTED,
                    detail="JavaScript is not type-checked",
                )
            )
        output.diagnostics = [self._convert(context, item) for item in items]
        return output

    @staticmethod
    def _convert(context: AnalysisContext, item: dict[str, Any]) -> Any:
        start = item.get("start") or {}
        end = item.get("end") or {}
        code = item.get("code")
        return make_diagnostic(
            context=context,
            severity=_SEVERITIES.get(str(item.get("severity")), Severity.ERROR),
            message=str(item.get("message", "")),
            source=SOURCE,
            category=_CATEGORIES.get(str(item.get("category")), DiagnosticCategory.SEMANTIC),
            code=f"TS{code}" if code is not None else None,
            line=int(start.get("line", 1)),
            column=int(start.get("column", 1)),
            end_line=int(end.get("line", start.get("line", 1))),
            end_column=int(end.get("column", start.get("column", 1))),
            metadata={"unnecessary": True} if item.get("unnecessary") else {},
        )
