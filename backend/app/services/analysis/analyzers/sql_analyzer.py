"""SQL syntax checking with sqlglot's parser (generic dialect).

SQL dialects differ, so statements that are valid in a specific database may not
parse with the generic dialect. Problems are therefore reported as warnings, and
the message names the dialect used.
"""

from __future__ import annotations

import re
from importlib.metadata import version

import sqlglot
from sqlglot.errors import ParseError, TokenError

from app.services.analysis.analyzers.base import AnalysisContext, AnalyzerOutput, make_diagnostic
from app.services.analysis.models import (
    AnalyzerInfo,
    Capability,
    CapabilityKind,
    CapabilityStatus,
    DiagnosticCategory,
    Severity,
)
from app.services.languages import Language

SOURCE = "sqlglot"

_REQUIRED_KEYWORD = re.compile(r"Required keyword: '(\w+)' missing for <class '[\w.]*?(\w+)'>")


def _readable(description: str) -> str:
    """sqlglot messages can mention internal class names; rephrase those."""
    match = _REQUIRED_KEYWORD.search(description)
    if match:
        return f"Incomplete {match.group(2).upper()} clause"
    return description


class SqlAnalyzer:
    name = "sql"
    languages = frozenset({Language.SQL})

    def info(self) -> list[AnalyzerInfo]:
        return [AnalyzerInfo(name=SOURCE, version=version("sqlglot"))]

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        output = AnalyzerOutput(
            capabilities=[
                Capability(
                    kind=CapabilityKind.SYNTAX,
                    status=CapabilityStatus.PERFORMED,
                    analyzer=SOURCE,
                    detail="Generic SQL dialect; database-specific syntax may be reported",
                ),
                Capability(kind=CapabilityKind.LINT, status=CapabilityStatus.NOT_SUPPORTED),
                Capability(
                    kind=CapabilityKind.SEMANTIC,
                    status=CapabilityStatus.NOT_SUPPORTED,
                    detail="Tables and columns are not checked against a schema",
                ),
            ]
        )
        if not context.source.strip():
            return output
        try:
            sqlglot.parse(context.source)
        except ParseError as exc:
            for error in exc.errors[:20] or [{}]:
                description = _readable(str(error.get("description") or "Unable to parse statement"))
                line = int(error.get("line") or 1)
                end_column = int(error.get("col") or 1)
                highlight = str(error.get("highlight") or "")
                start_column = max(1, end_column - len(highlight) + 1) if highlight else end_column
                output.diagnostics.append(
                    make_diagnostic(
                        context=context,
                        severity=Severity.WARNING,
                        message=f"SQL syntax (generic dialect): {description}",
                        source=SOURCE,
                        category=DiagnosticCategory.SYNTAX,
                        code="parse-error",
                        line=line,
                        column=start_column,
                        end_column=end_column + 1,
                    )
                )
        except TokenError as exc:
            output.diagnostics.append(
                make_diagnostic(
                    context=context,
                    severity=Severity.WARNING,
                    message=f"SQL syntax (generic dialect): {exc}",
                    source=SOURCE,
                    category=DiagnosticCategory.SYNTAX,
                    code="token-error",
                    line=1,
                    column=1,
                )
            )
        return output
