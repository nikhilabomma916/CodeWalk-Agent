from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.base import Base
from tests.db.conftest import alembic_config

TABLES = {"projects", "files", "analyses", "diagnostics"}


def test_migrations_upgrade_downgrade_roundtrip(database_url: str, engine: Engine) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    assert TABLES.isdisjoint(inspect(engine).get_table_names())

    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) >= TABLES | {"alembic_version"}


def test_models_match_migrations(engine: Engine) -> None:
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []


def test_expected_constraints_and_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    file_uniques = {u["name"] for u in inspector.get_unique_constraints("files")}
    assert "uq_files_project_id_path" in file_uniques
    assert "uq_projects_lower_name" in {i["name"] for i in inspector.get_indexes("projects")}
    assert {"ix_analyses_project_id_created_at", "ix_analyses_file_id_created_at"} <= {
        i["name"] for i in inspector.get_indexes("analyses")
    }
    foreign_keys = {
        fk["referred_table"]: fk["options"].get("ondelete") for fk in inspector.get_foreign_keys("analyses")
    }
    assert foreign_keys == {"projects": "CASCADE", "files": "SET NULL"}
    checks = {c["name"] for c in inspector.get_check_constraints("diagnostics")}
    assert checks == {"ck_diagnostics_diagnostic_severity", "ck_diagnostics_diagnostic_category"}
