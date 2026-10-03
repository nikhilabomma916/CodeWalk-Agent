"""Maps languages to their analyzers."""

from __future__ import annotations

from collections.abc import Iterable

from app.services.analysis.analyzers.base import Analyzer
from app.services.languages import Language


class AnalyzerRegistry:
    def __init__(self, analyzers: Iterable[Analyzer] = ()) -> None:
        self._by_language: dict[Language, list[Analyzer]] = {}
        self._analyzers: list[Analyzer] = []
        for analyzer in analyzers:
            self.register(analyzer)

    def register(self, analyzer: Analyzer) -> None:
        self._analyzers.append(analyzer)
        for language in analyzer.languages:
            self._by_language.setdefault(language, []).append(analyzer)

    def for_language(self, language: Language) -> list[Analyzer]:
        return list(self._by_language.get(language, ()))

    def supported_languages(self) -> list[Language]:
        return sorted(self._by_language)

    @property
    def analyzers(self) -> list[Analyzer]:
        return list(self._analyzers)
