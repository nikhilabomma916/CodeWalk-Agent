"""Python syntax + static analysis.

Pipeline: compile() for syntax errors first (pyflakes needs a valid AST to
lint, so there is no point running it over unparsable source), then
pyflakes for undefined names, unused imports/variables, and redefinitions.
"""

from __future__ import annotations

from pyflakes.api import check as pyflakes_check
from pyflakes.messages import Message as PyflakesMessage
from pyflakes.reporter import Reporter as PyflakesReporterBase

from code_analysis.analyzers.base import LanguageAnalyzer
from code_analysis.models import Diagnostic, Severity

# pyflakes message classes that indicate a likely-unused artifact rather than
# a real correctness problem; downgraded to "suggestion" instead of "warning".
_SUGGESTION_MESSAGE_NAMES = {
    "UnusedImport",
    "UnusedVariable",
    "UnusedAnnotation",
}


class _CollectingReporter(PyflakesReporterBase):
    """pyflakes reporter that collects Diagnostics instead of printing."""

    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []

    def flake(self, message: PyflakesMessage) -> None:
        message_name = type(message).__name__
        severity = (
            Severity.SUGGESTION if message_name in _SUGGESTION_MESSAGE_NAMES else Severity.WARNING
        )
        self.diagnostics.append(
            Diagnostic(
                severity=severity,
                message=message.message % message.message_args,
                line=message.lineno,
                column=message.col,
                source="pyflakes",
                code=message_name,
            )
        )

    def unexpectedError(self, filename: str, msg: str) -> None:
        self.diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                message=f"Static analysis could not complete: {msg}",
                line=1,
                column=None,
                source="pyflakes",
                code="UnexpectedError",
            )
        )

    def syntaxError(self, filename: str, msg: str, lineno: int, offset: int | None, text: str | None) -> None:
        # Syntax errors are already handled by PythonAnalyzer.analyze() via
        # compile(); pyflakes only reaches here if source slipped through
        # some other way, so still surface it rather than dropping it.
        self.diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                message=msg,
                line=lineno or 1,
                column=(offset - 1) if offset else None,
                source="syntax",
                code="SyntaxError",
            )
        )


class PythonAnalyzer(LanguageAnalyzer):
    language = "python"

    def analyze(self, source: str, file_path: str | None = None) -> list[Diagnostic]:
        filename = file_path or "<snippet>"

        syntax_diagnostic = self._check_syntax(source, filename)
        if syntax_diagnostic is not None:
            return [syntax_diagnostic]

        return self._lint(source, filename)

    def _check_syntax(self, source: str, filename: str) -> Diagnostic | None:
        try:
            compile(source, filename, "exec")
        except SyntaxError as exc:
            return Diagnostic(
                severity=Severity.ERROR,
                message=exc.msg,
                line=exc.lineno or 1,
                column=(exc.offset - 1) if exc.offset else None,
                source="syntax",
                code=type(exc).__name__,
            )
        except ValueError as exc:
            # e.g. null bytes in source
            return Diagnostic(
                severity=Severity.ERROR,
                message=str(exc),
                line=1,
                column=None,
                source="syntax",
                code="ValueError",
            )
        return None

    def _lint(self, source: str, filename: str) -> list[Diagnostic]:
        reporter = _CollectingReporter()
        pyflakes_check(source, filename, reporter)
        return reporter.diagnostics
