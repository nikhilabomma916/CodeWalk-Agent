"""Python structure extraction with the standard-library ``ast`` module."""

from __future__ import annotations

import ast
import warnings

from app.services.project_intelligence.models import (
    CodeSymbol,
    FileStructure,
    ImportKind,
    ImportRecord,
    SymbolKind,
)

MAX_SIGNATURE_LENGTH = 240


def _clip(text: str) -> str:
    return text if len(text) <= MAX_SIGNATURE_LENGTH else text[: MAX_SIGNATURE_LENGTH - 1] + "…"


def _parameters(arguments: ast.arguments) -> list[str]:
    names = [arg.arg for arg in (*arguments.posonlyargs, *arguments.args)]
    if arguments.vararg:
        names.append(f"*{arguments.vararg.arg}")
    names.extend(arg.arg for arg in arguments.kwonlyargs)
    if arguments.kwarg:
        names.append(f"**{arguments.kwarg.arg}")
    return names


class _Extractor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.symbols: list[CodeSymbol] = []
        self.imports: list[ImportRecord] = []
        self._scope: list[tuple[str, SymbolKind, str]] = []  # (qualified name, kind, id)

    def _add(self, node: ast.stmt | ast.expr, name: str, kind: SymbolKind, **extra: object) -> CodeSymbol:
        parent = self._scope[-1] if self._scope else None
        qualified = f"{parent[0]}.{name}" if parent else name
        symbol = CodeSymbol(
            id=f"{self.path}::{qualified}",
            name=name,
            qualified_name=qualified,
            kind=kind,
            file_path=self.path,
            line=node.lineno,
            column=node.col_offset + 1,
            end_line=node.end_lineno or node.lineno,
            end_column=(node.end_col_offset or node.col_offset) + 1,
            parent=parent[2] if parent else None,
            **extra,  # type: ignore[arg-type]
        )
        self.symbols.append(symbol)
        return symbol

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [ast.unparse(base) for base in node.bases] + [ast.unparse(k) for k in node.keywords]
        symbol = self._add(
            node,
            node.name,
            SymbolKind.CLASS,
            signature=_clip(f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"),
            decorators=[ast.unparse(d) for d in node.decorator_list],
        )
        self._scope.append((symbol.qualified_name, SymbolKind.CLASS, symbol.id))
        self.generic_visit(node)
        self._scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        in_class = bool(self._scope) and self._scope[-1][1] is SymbolKind.CLASS
        returns = ast.unparse(node.returns) if node.returns else None
        prefix = "async def" if is_async else "def"
        signature = f"{prefix} {node.name}({ast.unparse(node.args)})" + (f" -> {returns}" if returns else "")
        symbol = self._add(
            node,
            node.name,
            SymbolKind.METHOD if in_class else SymbolKind.FUNCTION,
            signature=_clip(signature),
            is_async=is_async,
            decorators=[ast.unparse(d) for d in node.decorator_list],
            parameters=_parameters(node.args),
            return_annotation=returns,
        )
        self._scope.append((symbol.qualified_name, symbol.kind, symbol.id))
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._scope:  # module-level variables only
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._add(target, target.id, SymbolKind.VARIABLE)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if not self._scope and isinstance(node.target, ast.Name):
            self._add(
                node.target,
                node.target.id,
                SymbolKind.VARIABLE,
                signature=_clip(f"{node.target.id}: {ast.unparse(node.annotation)}"),
            )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ImportRecord(
                    module=alias.name,
                    names=[alias.asname or alias.name],
                    kind=ImportKind.IMPORT,
                    line=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append(
            ImportRecord(
                module=node.module or "",
                names=[alias.name for alias in node.names],
                kind=ImportKind.FROM_IMPORT,
                line=node.lineno,
                level=node.level,
            )
        )


def extract_python_structure(path: str, source: str) -> FileStructure:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # e.g. invalid escape sequences; not structural
            tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        message = getattr(exc, "msg", None) or str(exc)
        return FileStructure(
            parse_error=f"{type(exc).__name__} on line {line}: {message}" if line else message
        )
    extractor = _Extractor(path)
    extractor.visit(tree)
    return FileStructure(symbols=extractor.symbols, imports=extractor.imports)
