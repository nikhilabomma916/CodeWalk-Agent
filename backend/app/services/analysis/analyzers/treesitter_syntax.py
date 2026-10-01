"""Parser-based syntax checking for Java, C, C++ and CSS using tree-sitter.

This is syntax analysis only: it finds code the grammar cannot parse. It does not
compile, resolve types, or evaluate the C/C++ preprocessor, so heavy macro usage
can occasionally confuse the parser.
"""

from __future__ import annotations

from tree_sitter import Node

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
from app.services.treesitter import grammar_package, grammar_version, new_parser

MAX_SYNTAX_DIAGNOSTICS = 50

_NOTES = {
    Language.JAVA: "Parser-based; no compilation or type resolution",
    Language.C: "Parser-based; the preprocessor is not evaluated",
    Language.CPP: "Parser-based; the preprocessor and templates are not evaluated",
    Language.CSS: "Parser-based; property names and values are not validated",
}


def _snippet(node: Node, limit: int = 30) -> str:
    text = (node.text or b"").decode("utf-8", errors="replace").strip()
    first_line = text.splitlines()[0] if text else ""
    return first_line if len(first_line) <= limit else first_line[:limit] + "…"


def collect_syntax_errors(root: Node, limit: int = MAX_SYNTAX_DIAGNOSTICS) -> list[tuple[Node, str]]:
    """Outermost ERROR nodes and MISSING nodes, in document order."""
    found: list[tuple[Node, str]] = []
    stack = [root]
    while stack and len(found) < limit:
        node = stack.pop()
        if node.is_missing:
            found.append((node, f"Missing '{node.type}'"))
            continue
        if node.is_error:
            snippet = _snippet(node)
            found.append((node, f"Unable to parse '{snippet}'" if snippet else "Unexpected token"))
            continue
        if node.has_error:
            stack.extend(reversed(node.children))
    return found


class TreeSitterSyntaxAnalyzer:
    name = "tree-sitter"
    languages = frozenset({Language.JAVA, Language.C, Language.CPP, Language.CSS})

    def info(self) -> list[AnalyzerInfo]:
        return [
            AnalyzerInfo(name=grammar_package(language), version=grammar_version(language))
            for language in sorted(self.languages)
        ]

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        source_name = grammar_package(context.language)
        tree = new_parser(context.language).parse(context.source.encode("utf-8"))
        output = AnalyzerOutput(
            capabilities=[
                Capability(
                    kind=CapabilityKind.SYNTAX,
                    status=CapabilityStatus.PERFORMED,
                    analyzer=source_name,
                    detail=_NOTES[context.language],
                ),
                Capability(kind=CapabilityKind.LINT, status=CapabilityStatus.NOT_SUPPORTED),
                Capability(kind=CapabilityKind.TYPES, status=CapabilityStatus.NOT_SUPPORTED),
            ]
        )
        if not tree.root_node.has_error:
            return output

        # tree-sitter points are 0-based rows and byte columns; convert byte
        # columns to character columns using the line text.
        lines = context.source.split("\n")

        def to_position(row: int, byte_column: int) -> tuple[int, int]:
            line_text = lines[row] if row < len(lines) else ""
            column = len(line_text.encode("utf-8")[:byte_column].decode("utf-8", errors="ignore"))
            return row + 1, column + 1

        for node, message in collect_syntax_errors(tree.root_node):
            line, column = to_position(*node.start_point)
            end_line, end_column = to_position(*node.end_point)
            output.diagnostics.append(
                make_diagnostic(
                    context=context,
                    severity=Severity.ERROR,
                    message=f"Syntax error: {message}",
                    source=source_name,
                    category=DiagnosticCategory.SYNTAX,
                    code="missing-token" if node.is_missing else "syntax-error",
                    line=line,
                    column=column,
                    end_line=end_line,
                    end_column=end_column,
                )
            )
        return output
