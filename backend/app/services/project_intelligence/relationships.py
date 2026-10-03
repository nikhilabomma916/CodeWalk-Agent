"""Import resolution and relationship building.

This is import analysis only: an ``imports`` relationship means a file imports
another project file (or an external module). It does not track calls or data flow.
"""

from __future__ import annotations

import json
import posixpath
from collections.abc import Iterable, Mapping
from typing import Any

from app.services.analysis.analyzers.json_analyzer import strip_jsonc
from app.services.languages import Language
from app.services.project_intelligence.models import (
    FileStructure,
    ImportKind,
    ImportRecord,
    Relationship,
    RelationshipKind,
    TargetKind,
)

JS_EXTENSIONS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".json")
JS_LANGUAGES = frozenset(
    {Language.JAVASCRIPT, Language.JAVASCRIPT_REACT, Language.TYPESCRIPT, Language.TYPESCRIPT_REACT}
)


def _dirname(path: str) -> str:
    return posixpath.dirname(path)


def _join(base: str, *parts: str) -> str:
    joined = posixpath.normpath(posixpath.join(base, *parts)) if base or parts else ""
    return "" if joined == "." else joined


class PythonImportResolver:
    def __init__(self, paths: Iterable[str]) -> None:
        self.paths = frozenset(paths)
        packages = {_dirname(p) for p in self.paths if posixpath.basename(p) == "__init__.py"}
        # A source root is the parent of a top-level package (e.g. "backend" for backend/app/...).
        roots = {""} | {_dirname(package) for package in packages if _dirname(package) not in packages}
        self.roots = sorted(roots, key=len, reverse=True)

    def module_file(self, base: str, dotted: str) -> str | None:
        relative = dotted.replace(".", "/")
        for candidate in (f"{relative}.py", f"{relative}.pyi", f"{relative}/__init__.py"):
            path = _join(base, candidate)
            if path in self.paths:
                return path
        return None

    def _bases(self, importer: str) -> list[str]:
        own = _dirname(importer)
        ancestors = [root for root in self.roots if not root or own == root or own.startswith(root + "/")]
        others = [root for root in self.roots if root not in ancestors]
        return list(dict.fromkeys([own, *ancestors, *others]))

    def resolve(self, importer: str, record: ImportRecord) -> tuple[str | None, list[str]]:
        """Returns (module file, submodule files imported by name)."""
        if record.level > 0:
            base = _dirname(importer)
            for _ in range(record.level - 1):
                base = _dirname(base)
            bases = [base]
            module_path = self.module_file(base, record.module) if record.module else None
            if not record.module:
                init = _join(base, "__init__.py")
                module_path = init if init in self.paths else None
        else:
            bases = self._bases(importer)
            module_path = next((p for b in bases if (p := self.module_file(b, record.module))), None)

        submodules: list[str] = []
        if record.kind is ImportKind.FROM_IMPORT:
            for name in record.names:
                if name == "*":
                    continue
                dotted = f"{record.module}.{name}" if record.module else name
                found = next((p for b in bases if (p := self.module_file(b, dotted))), None)
                if found:
                    submodules.append(found)
        return module_path, submodules


class JavaScriptImportResolver:
    def __init__(self, paths: Iterable[str], contents: Mapping[str, str | None]) -> None:
        self.paths = frozenset(paths)
        self._configs: dict[str, dict[str, Any] | None] = {}
        self._contents = contents

    def _file(self, base: str) -> str | None:
        candidates = [base]
        if base.endswith((".js", ".jsx", ".mjs", ".cjs")):
            stem = base.rsplit(".", 1)[0]
            candidates += [stem + ".ts", stem + ".tsx", stem + ".d.ts"]  # ESM TypeScript convention
        candidates += [base + extension for extension in JS_EXTENSIONS]
        candidates += [f"{base}/index{extension}" for extension in JS_EXTENSIONS]
        return next((candidate for candidate in candidates if candidate in self.paths), None)

    def _config(self, directory: str) -> tuple[str, dict[str, Any]] | None:
        """Nearest tsconfig.json / jsconfig.json compilerOptions at or above ``directory``."""
        current = directory
        while True:
            if current not in self._configs:
                self._configs[current] = None
                for name in ("tsconfig.json", "jsconfig.json"):
                    content = self._contents.get(_join(current, name))
                    if content:
                        try:
                            options = json.loads(strip_jsonc(content)).get("compilerOptions") or {}
                        except (ValueError, AttributeError):
                            options = {}
                        self._configs[current] = options if isinstance(options, dict) else {}
                        break
            options = self._configs[current]
            if options is not None:
                return current, options
            if not current:
                return None
            current = _dirname(current)

    def resolve(self, importer: str, specifier: str) -> str | None:
        if specifier.startswith(("./", "../")) or specifier in (".", ".."):
            target = _join(_dirname(importer), specifier)
            return None if target.startswith("..") else self._file(target)
        found = self._config(_dirname(importer))
        if found is None:
            return None
        config_dir, options = found
        base_url = _join(config_dir, str(options.get("baseUrl") or "."))
        paths = options.get("paths")
        if isinstance(paths, dict):
            for pattern, targets in paths.items():
                if not isinstance(pattern, str) or not isinstance(targets, list):
                    continue
                prefix, star, suffix = pattern.partition("*")
                matched = (
                    specifier == pattern
                    if not star
                    else (specifier.startswith(prefix) and specifier.endswith(suffix))
                )
                if not matched:
                    continue
                wildcard = specifier[len(prefix) : len(specifier) - len(suffix)] if star else ""
                for target in targets:
                    if isinstance(target, str):
                        resolved = self._file(_join(base_url, target.replace("*", wildcard)))
                        if resolved:
                            return resolved
        if options.get("baseUrl"):
            return self._file(_join(base_url, specifier))
        return None


def build_relationships(
    structures: Mapping[str, FileStructure],
    languages: Mapping[str, Language],
    contents: Mapping[str, str | None],
) -> list[Relationship]:
    """Resolve every import in-place (sets ``resolved_path``) and return all relationships."""
    paths = list(languages)
    python = PythonImportResolver(p for p in paths if languages[p] is Language.PYTHON)
    javascript = JavaScriptImportResolver(paths, contents)
    relationships: list[Relationship] = []

    for path, structure in structures.items():
        language = languages[path]
        for symbol in structure.symbols:
            if symbol.parent is None:
                relationships.append(
                    Relationship(
                        source=path,
                        target=symbol.id,
                        kind=RelationshipKind.DEFINES,
                        target_kind=TargetKind.SYMBOL,
                        line=symbol.line,
                    )
                )
            else:
                relationships.append(
                    Relationship(
                        source=symbol.parent,
                        target=symbol.id,
                        kind=RelationshipKind.CONTAINS,
                        target_kind=TargetKind.SYMBOL,
                        line=symbol.line,
                    )
                )
        for record in structure.imports:
            targets: list[str] = []
            if language is Language.PYTHON:
                module_path, submodules = python.resolve(path, record)
                record.resolved_path = submodules[0] if submodules and not module_path else module_path
                targets = [t for t in [module_path, *submodules] if t]
            elif language in JS_LANGUAGES:
                record.resolved_path = javascript.resolve(path, record.module)
                targets = [record.resolved_path] if record.resolved_path else []
            if targets:
                for target in dict.fromkeys(targets):
                    if target != path:
                        relationships.append(
                            Relationship(
                                source=path,
                                target=target,
                                kind=RelationshipKind.IMPORTS,
                                target_kind=TargetKind.FILE,
                                line=record.line,
                            )
                        )
            else:
                module = (
                    ("." * record.level + record.module) if language is Language.PYTHON else record.module
                )
                relationships.append(
                    Relationship(
                        source=path,
                        target=module or ".",
                        kind=RelationshipKind.IMPORTS,
                        target_kind=TargetKind.MODULE,
                        line=record.line,
                    )
                )
    return relationships
