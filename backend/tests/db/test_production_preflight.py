"""Module 22: the preflight's database checks against real PostgreSQL with pgvector."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app import preflight
from tests.conftest import make_settings


def test_database_pgvector_and_schema_pass_on_a_migrated_database(database_url: str, engine: Engine) -> None:
    checks = {
        check.name: check for check in preflight.database_checks(make_settings(database_url=database_url))
    }
    assert checks["database"].status == "PASS"
    assert checks["pgvector"].status == "PASS"
    assert checks["schema"].status == "PASS"
    assert "postgres" not in checks["database"].detail.lower().replace("postgresql", "")  # no URL parts


def test_a_database_behind_head_fails_the_schema_check(database_url: str, engine: Engine) -> None:
    with engine.begin() as connection:
        current: str = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        connection.execute(text("UPDATE alembic_version SET version_num = 'c5d2e8f1a9b3'"))
    try:
        checks = {
            check.name: check for check in preflight.database_checks(make_settings(database_url=database_url))
        }
        assert checks["schema"].status == "FAIL"
        assert "c5d2e8f1a9b3" in checks["schema"].detail
    finally:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": current})


def test_an_unreachable_database_fails_without_leaking_the_url() -> None:
    url = "postgresql+psycopg://user:hunter2-password@127.0.0.1:1/nothing"
    checks = preflight.database_checks(make_settings(database_url=url, database_connect_timeout_seconds=1))
    assert [check.status for check in checks] == ["FAIL"]
    assert "hunter2" not in checks[0].detail
