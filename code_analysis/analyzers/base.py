"""Abstract base for per-language analyzers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from code_analysis.models import Diagnostic


class LanguageAnalyzer(ABC):
    """A LanguageAnalyzer turns source text into a list of Diagnostics.

    Subclasses own one language's syntax/lint pipeline. The engine only
    depends on this interface, so adding a new language never requires
    touching engine.py.
    """

    language: str

    @abstractmethod
    def analyze(self, source: str, file_path: str | None = None) -> list[Diagnostic]:
        """Return diagnostics for the given source text."""
        raise NotImplementedError
