"""Basic structural HTML validation built on the standard-library tokenizer.

Checks: unclosed elements, mismatched or unexpected closing tags, end tags on
void elements, duplicate attributes, and duplicate ``id`` values. It is not a
full HTML5 conformance checker (content models and attribute values are not
validated), and elements whose end tag is optional in HTML are allowed to stay open.
"""

from __future__ import annotations

from html.parser import HTMLParser

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

SOURCE = "codewalk-html"

VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
        "keygen",
    }
)
OPTIONAL_END_TAGS = frozenset(
    {
        "html",
        "head",
        "body",
        "p",
        "li",
        "dt",
        "dd",
        "option",
        "optgroup",
        "tr",
        "td",
        "th",
        "thead",
        "tbody",
        "tfoot",
        "colgroup",
        "caption",
        "rt",
        "rp",
    }
)
FOREIGN_ROOTS = frozenset({"svg", "math"})


class _StructureChecker(HTMLParser):
    def __init__(self, context: AnalysisContext, output: AnalyzerOutput) -> None:
        super().__init__(convert_charrefs=True)
        self.context = context
        self.output = output
        self.stack: list[tuple[str, int, int]] = []
        self.ids: dict[str, int] = {}

    def _report(
        self, severity: Severity, message: str, code: str, line: int, column: int, length: int
    ) -> None:
        self.output.diagnostics.append(
            make_diagnostic(
                context=self.context,
                severity=severity,
                message=message,
                source=SOURCE,
                category=DiagnosticCategory.SYNTAX if severity is Severity.ERROR else DiagnosticCategory.LINT,
                code=code,
                line=line,
                column=column,
                end_column=column + max(length, 1),
            )
        )

    def _position(self) -> tuple[int, int]:
        line, offset = self.getpos()
        return line, offset + 1

    def _in_foreign_content(self) -> bool:
        return any(tag in FOREIGN_ROOTS for tag, _, _ in self.stack)

    def _check_attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line, column = self._position()
        seen: set[str] = set()
        for name, value in attrs:
            if name in seen:
                self._report(
                    Severity.WARNING,
                    f'Duplicate attribute "{name}" on <{tag}>',
                    "duplicate-attribute",
                    line,
                    column,
                    len(tag) + 1,
                )
            seen.add(name)
            if name == "id" and value:
                if value in self.ids:
                    self._report(
                        Severity.WARNING,
                        f'Duplicate id "{value}" (first used on line {self.ids[value]})',
                        "duplicate-id",
                        line,
                        column,
                        len(tag) + 1,
                    )
                else:
                    self.ids[value] = line

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_attributes(tag, attrs)
        if tag not in VOID_ELEMENTS:
            line, column = self._position()
            self.stack.append((tag, line, column))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_attributes(tag, attrs)
        if tag in VOID_ELEMENTS or self._in_foreign_content() or tag in FOREIGN_ROOTS:
            return
        line, column = self._position()
        self._report(
            Severity.WARNING,
            f"Self-closing syntax has no effect on <{tag}>; it stays open until </{tag}>",
            "non-void-self-closing",
            line,
            column,
            len(tag) + 1,
        )
        self.stack.append((tag, line, column))

    def handle_endtag(self, tag: str) -> None:
        line, column = self._position()
        if tag in VOID_ELEMENTS:
            self._report(
                Severity.WARNING,
                f"<{tag}> is a void element and must not have a closing tag",
                "void-end-tag",
                line,
                column,
                len(tag) + 3,
            )
            return
        for depth in range(len(self.stack) - 1, -1, -1):
            if self.stack[depth][0] == tag:
                for open_tag, open_line, open_column in self.stack[depth + 1 :]:
                    if open_tag not in OPTIONAL_END_TAGS:
                        self._report(
                            Severity.ERROR,
                            f"<{open_tag}> (line {open_line}) is not closed before </{tag}>",
                            "unclosed-element",
                            open_line,
                            open_column,
                            len(open_tag) + 1,
                        )
                del self.stack[depth:]
                return
        self._report(
            Severity.ERROR,
            f"Unexpected closing tag </{tag}> with no matching opening tag",
            "unexpected-end-tag",
            line,
            column,
            len(tag) + 3,
        )

    def finish(self) -> None:
        self.close()
        for tag, line, column in self.stack:
            if tag not in OPTIONAL_END_TAGS:
                self._report(
                    Severity.ERROR, f"<{tag}> is never closed", "unclosed-element", line, column, len(tag) + 1
                )


class HtmlAnalyzer:
    name = "html"
    languages = frozenset({Language.HTML})

    def info(self) -> list[AnalyzerInfo]:
        return [AnalyzerInfo(name=SOURCE, version="1")]

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        output = AnalyzerOutput(
            capabilities=[
                Capability(
                    kind=CapabilityKind.SYNTAX,
                    status=CapabilityStatus.PERFORMED,
                    analyzer=SOURCE,
                    detail="Tag structure only; not a full HTML5 conformance check",
                ),
                Capability(
                    kind=CapabilityKind.LINT,
                    status=CapabilityStatus.PERFORMED,
                    analyzer=SOURCE,
                    detail="Duplicate ids and attributes",
                ),
                Capability(kind=CapabilityKind.TYPES, status=CapabilityStatus.NOT_SUPPORTED),
            ]
        )
        checker = _StructureChecker(context, output)
        checker.feed(context.source)
        checker.finish()
        return output
