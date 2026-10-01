"""Basic Markdown lint rules (deterministic, line-based).

Rules (named after the equivalent markdownlint rules):
- MD001: heading levels should increase by one at a time
- MD018: missing space after '#' in an ATX heading
- MD025: more than one top-level (#) heading
- unclosed-fence: a fenced code block that is never closed

Markdown has no invalid syntax, so all findings are warnings or information.
"""

from __future__ import annotations

import re

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

SOURCE = "codewalk-markdown"
_HEADING = re.compile(r"^ {0,3}(#{1,6})(\s+|$)")
_MISSING_SPACE = re.compile(r"^ {0,3}(#{1,6})([^#\s])")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


class MarkdownAnalyzer:
    name = "markdown"
    languages = frozenset({Language.MARKDOWN})

    def info(self) -> list[AnalyzerInfo]:
        return [AnalyzerInfo(name=SOURCE, version="1")]

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        output = AnalyzerOutput(
            capabilities=[
                Capability(
                    kind=CapabilityKind.SYNTAX,
                    status=CapabilityStatus.NOT_SUPPORTED,
                    detail="Any text is valid Markdown",
                ),
                Capability(
                    kind=CapabilityKind.LINT,
                    status=CapabilityStatus.PERFORMED,
                    analyzer=SOURCE,
                    detail="Headings and code fences (MD001, MD018, MD025, unclosed fences)",
                ),
            ]
        )

        def report(
            severity: Severity, message: str, code: str, line: int, column: int = 1, length: int = 1
        ) -> None:
            output.diagnostics.append(
                make_diagnostic(
                    context=context,
                    severity=severity,
                    message=message,
                    source=SOURCE,
                    category=DiagnosticCategory.STYLE,
                    code=code,
                    line=line,
                    column=column,
                    end_column=column + length,
                )
            )

        fence: tuple[str, int] | None = None
        previous_level = 0
        top_level_line: int | None = None
        for number, text in enumerate(context.source.splitlines(), start=1):
            fence_match = _FENCE.match(text)
            if fence is not None:
                marker, _ = fence
                if (
                    fence_match
                    and fence_match.group(1)[0] == marker[0]
                    and len(fence_match.group(1)) >= len(marker)
                ):
                    fence = None
                continue
            if fence_match:
                fence = (fence_match.group(1), number)
                continue

            heading = _HEADING.match(text)
            if heading:
                level = len(heading.group(1))
                if previous_level and level > previous_level + 1:
                    report(
                        Severity.WARNING,
                        f"Heading level jumps from h{previous_level} to h{level}; use h{previous_level + 1}",
                        "MD001",
                        number,
                        1,
                        level,
                    )
                if level == 1:
                    if top_level_line is not None:
                        report(
                            Severity.INFORMATION,
                            f"Multiple top-level headings (first on line {top_level_line})",
                            "MD025",
                            number,
                            1,
                            1,
                        )
                    else:
                        top_level_line = number
                previous_level = level
            elif _MISSING_SPACE.match(text) and not text.lstrip().startswith("#!"):
                report(
                    Severity.WARNING,
                    "Missing space after '#' in heading",
                    "MD018",
                    number,
                    text.index("#") + 1,
                    1,
                )

        if fence is not None:
            report(
                Severity.WARNING, "Code block is never closed", "unclosed-fence", fence[1], 1, len(fence[0])
            )
        return output
