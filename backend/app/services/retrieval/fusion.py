"""Reciprocal rank fusion (RRF) of the deterministic and semantic result lists.

rrf(item) = sum over the lists that contain it of 1 / (K + rank), rank starting at 1.

Only ranks are combined, never the raw scores (deterministic points and cosine
similarities are not on the same scale). An item found by both lists is one
result. Ties are broken by the better deterministic rank, then the better
semantic rank, then the key.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass

K = 60

DESCRIPTION = (
    f"hybrid: reciprocal rank fusion, score = sum of 1 / ({K} + rank) over the deterministic "
    "and semantic lists that contain the result (rank starts at 1)."
)


@dataclass(frozen=True)
class Fused:
    key: Hashable
    score: float
    deterministic_rank: int | None
    semantic_rank: int | None


def rrf(deterministic: Sequence[Hashable], semantic: Sequence[Hashable]) -> list[Fused]:
    ranks: dict[Hashable, list[int | None]] = {}
    for rank, key in enumerate(deterministic, start=1):
        ranks.setdefault(key, [None, None])
        if ranks[key][0] is None:
            ranks[key][0] = rank
    for rank, key in enumerate(semantic, start=1):
        ranks.setdefault(key, [None, None])
        if ranks[key][1] is None:
            ranks[key][1] = rank
    fused = [
        Fused(
            key=key,
            score=sum(1 / (K + r) for r in (d, s) if r is not None),
            deterministic_rank=d,
            semantic_rank=s,
        )
        for key, (d, s) in ranks.items()
    ]
    missing = 10**9
    fused.sort(
        key=lambda f: (
            -f.score,
            f.deterministic_rank or missing,
            f.semantic_rank or missing,
            str(f.key),
        )
    )
    return fused
