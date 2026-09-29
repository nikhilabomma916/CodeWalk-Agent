"""Registry mapping language names to LanguageAnalyzer instances."""

from __future__ import annotations

from typing import Optional

from code_analysis.analyzers.base import LanguageAnalyzer
from code_analysis.analyzers.python_analyzer import PythonAnalyzer

_ANALYZERS: dict[str, LanguageAnalyzer] = {
    "python": PythonAnalyzer(),
}


def get_analyzer(language: str) -> Optional[LanguageAnalyzer]:
    """Look up the analyzer for a language name, or None if unsupported.

    Additional languages (JavaScript, TypeScript, ...) are added by
    registering a new LanguageAnalyzer here without touching engine.py.
    """

    return _ANALYZERS.get(language.lower())
