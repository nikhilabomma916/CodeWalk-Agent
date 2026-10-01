"""Python analysis.

1. Syntax: CPython's own parser (``ast.parse``); it never executes the code.
   Invalid escape sequences and similar ``SyntaxWarning``s are reported too.
2. Lint: Ruff (pyflakes, pycodestyle errors, bugbear), run as a subprocess that
   reads the source from stdin with ``--isolated``, so no project configuration
   files are read. Lint is skipped when the file has a syntax error.

Type checking (mypy) is deliberately not run on every edit; it is reported as
not supported for real-time analysis.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
import warnings
from functools import cache
from pathlib import PurePosixPath
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
from app.services.languages import Language

logger = logging.getLogger(__name__)

# pyflakes (F), pycodestyle runtime/statement errors (E4, E7, E9), warnings (W), bugbear (B).
RUFF_RULES = "F,E4,E7,E9,W,B"
PYTHON_TARGET = f"py{sys.version_info.major}{sys.version_info.minor}"

# Ruff codes that indicate code that will fail at runtime.
_ERROR_CODES = ("F821", "F822", "F823", "F63", "F7", "E9")
_INFO_PREFIXES = ("W29",)  # trailing / missing-newline whitespace


@cache
def _ruff_binary() -> str | None:
    try:
        from ruff.__main__ import find_ruff_bin  # type: ignore[import-untyped]

        return str(find_ruff_bin())
    except (ImportError, FileNotFoundError):
        return None


@cache
def ruff_version() -> str | None:
    binary = _ruff_binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - trusted binary, fixed arguments
            [binary, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip().removeprefix("ruff ") or None


def _ruff_severity(code: str | None) -> Severity:
    if code is None:
        return Severity.ERROR
    if code.startswith(_ERROR_CODES):
        return Severity.ERROR
    if code.startswith(_INFO_PREFIXES):
        return Severity.INFORMATION
    return Severity.WARNING


def _ruff_category(code: str) -> DiagnosticCategory:
    return DiagnosticCategory.STYLE if code.startswith(("W", "E")) else DiagnosticCategory.LINT


class PythonAnalyzer:
    name = "python"
    languages = frozenset({Language.PYTHON})

    def info(self) -> list[AnalyzerInfo]:
        return [
            AnalyzerInfo(name="python-ast", version=sys.version.split()[0]),
            AnalyzerInfo(name="ruff", version=ruff_version()),
        ]

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        output = AnalyzerOutput()
        output.capabilities.append(
            Capability(
                kind=CapabilityKind.TYPES,
                status=CapabilityStatus.NOT_SUPPORTED,
                detail="Type checking is not run during real-time analysis",
            )
        )

        syntax_warnings: list[Diagnostic] = []
        syntax_ok = self._check_syntax(context, output, syntax_warnings)
        output.capabilities.append(
            Capability(kind=CapabilityKind.SYNTAX, status=CapabilityStatus.PERFORMED, analyzer="python-ast")
        )
        if not syntax_ok:
            output.capabilities.append(
                Capability(
                    kind=CapabilityKind.LINT,
                    status=CapabilityStatus.SKIPPED,
                    analyzer="ruff",
                    detail="Fix syntax errors to enable linting",
                )
            )
            return output

        if not self._lint(context, output):
            # Ruff reports these too (W605); only surface the parser's copy without Ruff.
            output.diagnostics.extend(syntax_warnings)
        return output

    def _check_syntax(
        self, context: AnalysisContext, output: AnalyzerOutput, syntax_warnings: list[Diagnostic]
    ) -> bool:
        filename = context.file_path or "<editor>"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                ast.parse(context.source, filename=filename)
            except SyntaxError as exc:
                output.diagnostics.append(self._syntax_error(context, exc))
                return False
            except ValueError as exc:  # e.g. source contains NUL bytes
                output.diagnostics.append(
                    make_diagnostic(
                        context=context,
                        severity=Severity.ERROR,
                        message=str(exc),
                        source="python",
                        category=DiagnosticCategory.SYNTAX,
                        line=1,
                        column=1,
                    )
                )
                return False
        for warning in caught:
            if issubclass(warning.category, SyntaxWarning):
                syntax_warnings.append(
                    make_diagnostic(
                        context=context,
                        severity=Severity.WARNING,
                        message=str(warning.message),
                        source="python",
                        category=DiagnosticCategory.SYNTAX,
                        code="SyntaxWarning",
                        line=warning.lineno or 1,
                        column=1,
                    )
                )
        return True

    @staticmethod
    def _syntax_error(context: AnalysisContext, exc: SyntaxError) -> Diagnostic:
        kind = type(exc).__name__  # SyntaxError, IndentationError, TabError
        line = exc.lineno or 1
        column = exc.offset or 1
        end_line = exc.end_lineno or line
        end_column = exc.end_offset if exc.end_offset and exc.end_offset > 0 else None
        return make_diagnostic(
            context=context,
            severity=Severity.ERROR,
            message=exc.msg,
            source="python",
            category=DiagnosticCategory.SYNTAX,
            code=kind,
            line=line,
            column=column,
            end_line=end_line,
            end_column=end_column,
        )

    def _lint(self, context: AnalysisContext, output: AnalyzerOutput) -> bool:
        """Run Ruff; returns whether linting was performed."""
        binary = _ruff_binary()
        if binary is None:
            output.capabilities.append(
                Capability(
                    kind=CapabilityKind.LINT,
                    status=CapabilityStatus.UNAVAILABLE,
                    analyzer="ruff",
                    detail="Ruff is not installed",
                )
            )
            return False
        stdin_name = PurePosixPath(context.file_path).name if context.file_path else "editor.py"
        command = [
            binary,
            "check",
            "--isolated",
            "--no-cache",
            "--output-format",
            "json",
            "--select",
            RUFF_RULES,
            "--target-version",
            PYTHON_TARGET,
            "--stdin-filename",
            stdin_name,
            "-",
        ]
        try:
            completed = subprocess.run(  # noqa: S603 - trusted binary; source passed as data on stdin
                command,
                input=context.source,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=context.timeout_seconds,
                check=False,
            )
            items: list[dict[str, Any]] = json.loads(completed.stdout or "[]")
        except subprocess.TimeoutExpired:
            output.errors.append("Ruff timed out")
            output.capabilities.append(
                Capability(
                    kind=CapabilityKind.LINT,
                    status=CapabilityStatus.UNAVAILABLE,
                    analyzer="ruff",
                    detail="Timed out",
                )
            )
            return False
        except (OSError, ValueError):
            logger.exception("Ruff failed")
            output.errors.append("Ruff failed to run")
            output.capabilities.append(
                Capability(
                    kind=CapabilityKind.LINT,
                    status=CapabilityStatus.UNAVAILABLE,
                    analyzer="ruff",
                    detail="Failed to run",
                )
            )
            return False

        for item in items:
            code = item.get("code")
            if not code:
                continue  # syntax errors are reported by the CPython parser
            location = item.get("location") or {}
            end = item.get("end_location") or {}
            fix = item.get("fix")
            output.diagnostics.append(
                make_diagnostic(
                    context=context,
                    severity=_ruff_severity(code),
                    message=str(item.get("message", "")),
                    source="ruff",
                    category=_ruff_category(code),
                    code=code,
                    line=int(location.get("row", 1)),
                    column=int(location.get("column", 1)),
                    end_line=int(end.get("row", location.get("row", 1))),
                    end_column=int(end.get("column", location.get("column", 1))),
                    suggestion=fix.get("message") if isinstance(fix, dict) else None,
                    documentation_url=item.get("url"),
                    fixable=isinstance(fix, dict),
                )
            )
        output.capabilities.append(
            Capability(
                kind=CapabilityKind.LINT,
                status=CapabilityStatus.PERFORMED,
                analyzer="ruff",
                detail=f"rules {RUFF_RULES}",
            )
        )
        return True
