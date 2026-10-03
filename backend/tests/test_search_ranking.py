"""Deterministic search ranking primitives."""

from __future__ import annotations

import pytest

from app.schemas.search import MatchType
from app.services.project_search import ranking
from app.services.project_search.index import is_searchable


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("UserService", ["user", "service"]),
        ("calculate_total", ["calculate", "total"]),
        ("database connection", ["database", "connection"]),
        ("HTTPServerError", ["http", "server", "error"]),
        ("src/auth/routes.py", ["src", "auth", "routes", "py"]),
        ("a  a", ["a"]),
    ],
)
def test_terms(text: str, expected: list[str]) -> None:
    assert ranking.terms(text) == expected


def test_match_name_kinds() -> None:
    def kind(query: str, name: str) -> MatchType | None:
        match = ranking.match_name(query, ranking.terms(query), name)
        return match[0] if match else None

    assert kind("UserService", "UserService") is MatchType.SYMBOL_EXACT
    assert kind("user service", "UserService") is MatchType.SYMBOL_EXACT  # separators ignored
    assert kind("calc", "calculate_total") is MatchType.SYMBOL_PREFIX
    assert kind("payment controller", "PaymentController") is MatchType.SYMBOL_EXACT
    assert kind("auth user", "authenticate_user") is MatchType.SYMBOL_TOKENS
    assert kind("database connection", "open_database") is MatchType.SYMBOL_TOKENS
    assert kind("zebra", "UserService") is None


def test_scores_follow_the_documented_formula() -> None:
    match = ranking.match_name("database connection", ["database", "connection"], "open_database")
    assert match is not None
    _, share, _ = match
    assert share == 0.5
    assert ranking.score(MatchType.SYMBOL_TOKENS, share, 0) == 32.5
    assert ranking.score(MatchType.SYMBOL_EXACT, 1.0, ranking.CURRENT_FILE_BONUS) == 115
    assert (
        ranking.BASE[MatchType.SYMBOL_EXACT]
        > ranking.BASE[MatchType.FILE_NAME]
        > ranking.BASE[MatchType.TEXT]
    )
    assert "symbol_exact=100" in ranking.RANKING_DESCRIPTION


@pytest.mark.parametrize(
    ("path", "searchable"),
    [
        ("src/app.py", True),
        ("node_modules/pkg/index.js", False),
        ("app/__pycache__/x.py", False),
        ("config/.env", False),
        (".env.example", True),
    ],
)
def test_ignored_paths_are_not_searchable(path: str, searchable: bool) -> None:
    assert is_searchable(path) is searchable
