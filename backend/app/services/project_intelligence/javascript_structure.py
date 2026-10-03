"""JavaScript/TypeScript structure extraction from tree-sitter parse trees.

Extracted (the reliable subset, straight from the parse tree):
- top-level functions, classes (and their methods), interfaces, type aliases,
  enums, and variables (arrow/function-expression variables count as functions)
- ES imports, re-exports, ``require("x")`` and dynamic ``import("x")``
- exported names

Not extracted: symbols nested inside function bodies, object-literal methods,
and CommonJS ``module.exports`` assignments.
"""

from __future__ import annotations

from tree_sitter import Node

from app.services.languages import Language
from app.services.project_intelligence.models import (
    CodeSymbol,
    FileStructure,
    ImportKind,
    ImportRecord,
    SymbolKind,
)
from app.services.treesitter import new_parser

MAX_SIGNATURE_LENGTH = 240

_DECLARATION_KINDS = {
    "function_declaration": SymbolKind.FUNCTION,
    "generator_function_declaration": SymbolKind.FUNCTION,
    "class_declaration": SymbolKind.CLASS,
    "abstract_class_declaration": SymbolKind.CLASS,
    "interface_declaration": SymbolKind.INTERFACE,
    "type_alias_declaration": SymbolKind.TYPE_ALIAS,
    "enum_declaration": SymbolKind.ENUM,
}
_FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "function", "generator_function"})


def _text(node: Node | None) -> str:
    return (node.text or b"").decode("utf-8", errors="replace") if node is not None else ""


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_SIGNATURE_LENGTH else text[: MAX_SIGNATURE_LENGTH - 1] + "…"


def _string_value(node: Node | None) -> str | None:
    if node is None or node.type not in ("string", "template_string"):
        return None
    return _text(node)[1:-1]


def _is_async(node: Node) -> bool:
    return any(child.type == "async" for child in node.children)


def _parameters(node: Node | None) -> list[str]:
    if node is None:
        return []
    names = []
    for child in node.named_children:
        pattern = child.child_by_field_name("pattern") or child
        if child.type in (
            "identifier",
            "required_parameter",
            "optional_parameter",
            "assignment_pattern",
            "rest_pattern",
        ):
            if child.type == "assignment_pattern":
                pattern = child.child_by_field_name("left") or child
            names.append(_text(pattern))
    return names


class _Extractor:
    def __init__(self, path: str, source: bytes) -> None:
        self.path = path
        self._lines = source.split(b"\n")
        self.symbols: list[CodeSymbol] = []
        self.imports: list[ImportRecord] = []
        self.exports: list[str] = []

    def _position(self, node: Node) -> tuple[int, int, int, int]:
        """1-based line/column; tree-sitter columns are bytes, converted to characters."""

        def column(row: int, byte_column: int) -> int:
            line = self._lines[row] if row < len(self._lines) else b""
            return len(line[:byte_column].decode("utf-8", errors="ignore")) + 1

        (start_row, start_col), (end_row, end_col) = node.start_point, node.end_point
        return start_row + 1, column(start_row, start_col), end_row + 1, column(end_row, end_col)

    def _add(
        self,
        node: Node,
        name: str,
        kind: SymbolKind,
        *,
        parent: CodeSymbol | None = None,
        exported: bool | None = None,
        signature: str | None = None,
        parameters: list[str] | None = None,
        return_annotation: str | None = None,
        is_async: bool = False,
    ) -> CodeSymbol:
        qualified = f"{parent.qualified_name}.{name}" if parent else name
        line, column, end_line, end_column = self._position(node)
        symbol = CodeSymbol(
            id=f"{self.path}::{qualified}",
            name=name,
            qualified_name=qualified,
            kind=kind,
            file_path=self.path,
            line=line,
            column=column,
            end_line=end_line,
            end_column=end_column,
            parent=parent.id if parent else None,
            signature=_clip(signature) if signature else None,
            is_async=is_async,
            parameters=parameters or [],
            return_annotation=return_annotation,
            exported=exported,
        )
        self.symbols.append(symbol)
        return symbol

    def extract(self, root: Node) -> None:
        for node in root.named_children:
            self._top_level(node, exported=False)
        self._find_calls(root)

    def _top_level(self, node: Node, *, exported: bool) -> None:
        if node.type == "import_statement":
            self._import(node)
        elif node.type == "export_statement":
            self._export(node)
        elif node.type in _DECLARATION_KINDS:
            self._declaration(node, exported=exported)
        elif node.type in ("lexical_declaration", "variable_declaration"):
            self._variables(node, exported=exported)

    def _declaration(self, node: Node, *, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        name = _text(name_node) or "default"
        kind = _DECLARATION_KINDS[node.type]
        if exported:
            self.exports.append(name)
        if kind is SymbolKind.FUNCTION:
            params = node.child_by_field_name("parameters")
            returns = node.child_by_field_name("return_type")
            return_text = _text(returns).lstrip(":").strip() or None
            self._add(
                node,
                name,
                kind,
                exported=exported,
                is_async=_is_async(node),
                signature=f"function {name}{_text(params)}" + (f": {return_text}" if return_text else ""),
                parameters=_parameters(params),
                return_annotation=return_text,
            )
        elif kind is SymbolKind.CLASS:
            heritage = next((c for c in node.children if c.type == "class_heritage"), None)
            symbol = self._add(
                node, name, kind, exported=exported, signature=f"class {name} {_text(heritage)}".strip()
            )
            body = node.child_by_field_name("body")
            for member in body.named_children if body else []:
                if member.type in ("method_definition", "abstract_method_signature"):
                    params = member.child_by_field_name("parameters")
                    returns = member.child_by_field_name("return_type")
                    return_text = _text(returns).lstrip(":").strip() or None
                    method = _text(member.child_by_field_name("name"))
                    self._add(
                        member,
                        method,
                        SymbolKind.METHOD,
                        parent=symbol,
                        is_async=_is_async(member),
                        signature=f"{method}{_text(params)}" + (f": {return_text}" if return_text else ""),
                        parameters=_parameters(params),
                        return_annotation=return_text,
                    )
        else:
            self._add(node, name, kind, exported=exported, signature=_text(node).split("{")[0].split("=")[0])

    def _variables(self, node: Node, *, exported: bool) -> None:
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None or name_node.type != "identifier":
                continue  # destructuring patterns
            name = _text(name_node)
            value = declarator.child_by_field_name("value")
            if exported:
                self.exports.append(name)
            if value is not None and value.type in _FUNCTION_VALUES:
                params = value.child_by_field_name("parameters") or value.child_by_field_name("parameter")
                returns = value.child_by_field_name("return_type")
                return_text = _text(returns).lstrip(":").strip() or None
                self._add(
                    declarator,
                    name,
                    SymbolKind.FUNCTION,
                    exported=exported,
                    is_async=_is_async(value),
                    signature=f"const {name} = {_text(params)} =>",
                    parameters=_parameters(params),
                    return_annotation=return_text,
                )
            else:
                self._add(declarator, name, SymbolKind.VARIABLE, exported=exported)

    def _import(self, node: Node) -> None:
        source = _string_value(node.child_by_field_name("source"))
        if source is None:
            return
        names: list[str] = []
        clause = next((c for c in node.named_children if c.type == "import_clause"), None)
        for child in clause.named_children if clause else []:
            if child.type == "identifier":
                names.append(_text(child))
            elif child.type == "namespace_import":
                names.append("* as " + _text(child.named_children[-1]) if child.named_children else "*")
            elif child.type == "named_imports":
                names.extend(
                    _text(spec.child_by_field_name("name"))
                    for spec in child.named_children
                    if spec.type == "import_specifier"
                )
        self.imports.append(
            ImportRecord(module=source, names=names, kind=ImportKind.IMPORT, line=node.start_point[0] + 1)
        )

    def _export(self, node: Node) -> None:
        declaration = node.child_by_field_name("declaration")
        source = _string_value(node.child_by_field_name("source"))
        is_default = any(child.type == "default" for child in node.children)
        if declaration is not None:
            self._top_level(declaration, exported=True)
            if is_default and declaration.type in _DECLARATION_KINDS:
                self.exports.append("default")
            return
        clause = next((c for c in node.named_children if c.type == "export_clause"), None)
        exported_names = [
            _text(spec.child_by_field_name("alias") or spec.child_by_field_name("name"))
            for spec in (clause.named_children if clause else [])
            if spec.type == "export_specifier"
        ]
        if source is not None:
            self.imports.append(
                ImportRecord(
                    module=source,
                    names=exported_names or ["*"],
                    kind=ImportKind.REEXPORT,
                    line=node.start_point[0] + 1,
                )
            )
        if is_default:
            self.exports.append("default")
        self.exports.extend(exported_names)

    def _find_calls(self, root: Node) -> None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                function = node.child_by_field_name("function")
                arguments = node.child_by_field_name("arguments")
                first = arguments.named_children[0] if arguments and arguments.named_children else None
                specifier = _string_value(first)
                if function is not None and specifier is not None:
                    if function.type == "import":
                        self.imports.append(
                            ImportRecord(
                                module=specifier, kind=ImportKind.DYNAMIC, line=node.start_point[0] + 1
                            )
                        )
                    elif function.type == "identifier" and _text(function) == "require":
                        self.imports.append(
                            ImportRecord(
                                module=specifier, kind=ImportKind.REQUIRE, line=node.start_point[0] + 1
                            )
                        )
            stack.extend(node.named_children)


def extract_javascript_structure(path: str, source: str, language: Language) -> FileStructure:
    data = source.encode("utf-8")
    tree = new_parser(language).parse(data)
    extractor = _Extractor(path, data)
    extractor.extract(tree.root_node)
    extractor.imports.sort(key=lambda record: record.line)
    return FileStructure(
        symbols=extractor.symbols,
        imports=extractor.imports,
        exports=list(dict.fromkeys(extractor.exports)),
        parse_error="Syntax errors present; structure may be incomplete"
        if tree.root_node.has_error
        else None,
    )
