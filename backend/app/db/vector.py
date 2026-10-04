"""SQLAlchemy column type for pgvector's ``vector(n)``.

Values are sent as pgvector's text form (``[1.0,2.0,...]``) with an explicit cast,
and read back as ``list[float]``. Registering the type with the PostgreSQL dialect
lets reflection (Alembic autogenerate / ``alembic check``) recognise the column.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Float, cast, literal
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import UserDefinedType


# pgvector's text form is a JSON array of numbers, so the C-accelerated json module encodes and
# decodes it (a 1,024-dimension vector per chunk makes a Python loop the slow part of indexing).
def to_text(values: Sequence[float]) -> str:
    return json.dumps(list(map(float, values)), separators=(",", ":"))


def from_text(value: str) -> list[float]:
    return [float(v) for v in json.loads(value)]


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"VECTOR({self.dimensions})" if self.dimensions else "VECTOR"

    def bind_processor(self, dialect: Any) -> Callable[[Any], str | None]:
        def process(value: Any) -> str | None:
            return None if value is None else to_text(value)

        return process

    def bind_expression(self, bindvalue: Any) -> ColumnElement[Any]:
        return cast(bindvalue, self)

    def result_processor(self, dialect: Any, coltype: Any) -> Callable[[Any], list[float] | None]:
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            return from_text(value) if isinstance(value, str) else [float(v) for v in value]

        return process

    class comparator_factory(UserDefinedType.Comparator[list[float]]):  # noqa: N801 (SQLAlchemy API name)
        def cosine_distance(self, other: Sequence[float]) -> ColumnElement[float]:
            """pgvector ``<=>``: 1 - cosine similarity (0 = same direction)."""
            return self.expr.op("<=>", return_type=Float)(literal(list(other), Vector(len(other))))


ischema_names["vector"] = Vector
