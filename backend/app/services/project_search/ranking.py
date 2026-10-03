"""Deterministic, explainable ranking for project search.

score = BASE[match_type] x coverage + context_bonus

- coverage: share of query terms matched (1.0 for exact and prefix matches).
- context_bonus: CURRENT_FILE_BONUS for results in the open file,
  RELATED_FILE_BONUS for files it imports or that import it.

Terms come from splitting the query on non-alphanumerics, camelCase, and
snake_case ("UserService" -> user, service). A query term matches a name term
when the name term starts with it ("auth" matches "authenticate").
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.schemas.search import MatchType

BASE: dict[MatchType, int] = {
    MatchType.SYMBOL_EXACT: 100,
    MatchType.FILE_NAME: 90,
    MatchType.SYMBOL_PREFIX: 80,
    MatchType.SYMBOL_TOKENS: 65,
    MatchType.FILE_PATH: 55,
    MatchType.IMPORT: 40,
    MatchType.IDENTIFIER: 30,
    MatchType.TEXT: 20,
}
CURRENT_FILE_BONUS = 15
RELATED_FILE_BONUS = 10

RANKING_DESCRIPTION = (
    "score = base(match type) x coverage + context bonus. Bases: "
    + ", ".join(f"{t.value}={w}" for t, w in BASE.items())
    + f"; current file +{CURRENT_FILE_BONUS}, files related by imports +{RELATED_FILE_BONUS}. "
    "Ties are broken by path and line."
)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SPLIT = re.compile(r"[^A-Za-z0-9]+")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def terms(text: str) -> list[str]:
    """Lower-cased word parts of ``text``, in order, without duplicates."""
    seen: list[str] = []
    for chunk in _SPLIT.split(text):
        for part in _CAMEL.split(chunk):
            part = part.lower()
            if part and part not in seen:
                seen.append(part)
    return seen


def compact(text: str) -> str:
    """Lower-case text without separators: 'User Service' and 'user_service' -> 'userservice'."""
    return "".join(_SPLIT.split(text)).lower()


def coverage(query_terms: Sequence[str], name_terms: Sequence[str]) -> float:
    if not query_terms:
        return 0.0
    matched = sum(1 for q in query_terms if any(n.startswith(q) for n in name_terms))
    return matched / len(query_terms)


def match_name(query: str, query_terms: Sequence[str], name: str) -> tuple[MatchType, float, str] | None:
    """How a symbol name matches the query, if at all: (type, coverage, reason)."""
    if name.lower() == query.strip().lower() or compact(name) == compact(query):
        return MatchType.SYMBOL_EXACT, 1.0, "name equals the query (ignoring case and separators)"
    q = compact(query)
    if len(q) >= 2 and compact(name).startswith(q):
        return MatchType.SYMBOL_PREFIX, 1.0, "name starts with the query"
    share = coverage(query_terms, terms(name))
    if share > 0:
        matched = [t for t in query_terms if any(n.startswith(t) for n in terms(name))]
        return MatchType.SYMBOL_TOKENS, share, f"name contains {', '.join(matched)}"
    return None


def score(match_type: MatchType, share: float, bonus: int) -> float:
    return round(BASE[match_type] * share + bonus, 2)
