"""Tree-sitter grammars, bundled as compiled wheels (no runtime downloads)."""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from importlib.metadata import PackageNotFoundError, version

import tree_sitter_c
import tree_sitter_cpp
import tree_sitter_css
import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language as TSLanguage
from tree_sitter import Parser

from app.services.languages import Language

_GRAMMARS: dict[Language, tuple[str, Callable[[], object]]] = {
    Language.JAVA: ("tree-sitter-java", tree_sitter_java.language),
    Language.C: ("tree-sitter-c", tree_sitter_c.language),
    Language.CPP: ("tree-sitter-cpp", tree_sitter_cpp.language),
    Language.CSS: ("tree-sitter-css", tree_sitter_css.language),
    Language.JAVASCRIPT: ("tree-sitter-javascript", tree_sitter_javascript.language),
    # The JavaScript grammar includes JSX.
    Language.JAVASCRIPT_REACT: ("tree-sitter-javascript", tree_sitter_javascript.language),
    Language.TYPESCRIPT: ("tree-sitter-typescript", tree_sitter_typescript.language_typescript),
    Language.TYPESCRIPT_REACT: ("tree-sitter-typescript", tree_sitter_typescript.language_tsx),
}


def has_grammar(language: Language) -> bool:
    return language in _GRAMMARS


@cache
def _language(language: Language) -> TSLanguage:
    return TSLanguage(_GRAMMARS[language][1]())


def new_parser(language: Language) -> Parser:
    """A fresh parser (parsers are not thread-safe; languages are shared)."""
    return Parser(_language(language))


def grammar_package(language: Language) -> str:
    return _GRAMMARS[language][0]


@cache
def grammar_version(language: Language) -> str | None:
    try:
        return version(grammar_package(language))
    except PackageNotFoundError:
        return None
