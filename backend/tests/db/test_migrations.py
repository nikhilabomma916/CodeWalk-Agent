from __future__ import annotations

import argparse
import uuid

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from tests.db.conftest import alembic_config

TABLES = {
    "users",
    "auth_sessions",
    "projects",
    "files",
    "file_versions",
    "analyses",
    "diagnostics",
    "activity_events",
    "code_chunks",
}


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
    assert "uq_projects_owner_id_lower_name" in {i["name"] for i in inspector.get_indexes("projects")}
    assert "uq_users_email" in {u["name"] for u in inspector.get_unique_constraints("users")}
    assert "uq_auth_sessions_token_hash" in {
        u["name"] for u in inspector.get_unique_constraints("auth_sessions")
    }
    project_fks = {
        fk["referred_table"]: fk["options"].get("ondelete") for fk in inspector.get_foreign_keys("projects")
    }
    assert project_fks == {"users": "CASCADE"}
    event_fks = {
        fk["referred_table"]: fk["options"].get("ondelete")
        for fk in inspector.get_foreign_keys("activity_events")
    }
    assert event_fks == {
        "users": "CASCADE",
        "projects": "SET NULL",
        "files": "SET NULL",
        "analyses": "SET NULL",
    }
    assert {"ix_activity_events_user_id_created_at", "ix_activity_events_project_id_created_at"} <= {
        i["name"] for i in inspector.get_indexes("activity_events")
    }
    assert {"ix_analyses_project_id_created_at", "ix_analyses_file_id_created_at"} <= {
        i["name"] for i in inspector.get_indexes("analyses")
    }
    foreign_keys = {
        fk["referred_table"]: fk["options"].get("ondelete") for fk in inspector.get_foreign_keys("analyses")
    }
    assert foreign_keys == {"projects": "CASCADE", "files": "SET NULL"}
    checks = {c["name"] for c in inspector.get_check_constraints("diagnostics")}
    assert checks == {"ck_diagnostics_diagnostic_severity", "ck_diagnostics_diagnostic_category"}


def test_upgrade_refuses_to_orphan_existing_projects(database_url: str, engine: Engine) -> None:
    """Projects created before accounts existed block the upgrade unless deletion is requested."""
    config = alembic_config(database_url)
    command.downgrade(config, "32a816011f6f")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, name) VALUES (gen_random_uuid(), 'Legacy')"))
    try:
        with pytest.raises(RuntimeError, match="delete_unowned_projects"):
            command.upgrade(config, "head")
        config.cmd_opts = argparse.Namespace(x=["delete_unowned_projects=true"])
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM projects")) == 0
    finally:
        config.cmd_opts = None
        command.upgrade(config, "head")


def test_ai_types_migration(database_url: str, engine: Engine) -> None:
    """AI analysis/event types are accepted after upgrade and removed by downgrade."""
    config = alembic_config(database_url)
    insert_user = text(
        "INSERT INTO users (id, email, name, password_hash) VALUES (:id, 'm@example.com', 'M', 'x')"
    )
    insert_project = text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'P')")
    insert_analysis = text(
        "INSERT INTO analyses "
        "(id, project_id, analysis_type, status, duration_ms, diagnostic_count, details) "
        "VALUES (gen_random_uuid(), :project, :type, 'completed', 1, 0, '{}')"
    )
    insert_event = text(
        "INSERT INTO activity_events (id, user_id, event_type, project_name, details) "
        "VALUES (gen_random_uuid(), :user, :type, 'P', '{}')"
    )
    user, project = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(insert_user, {"id": user})
            connection.execute(insert_project, {"id": project, "owner": user})
            connection.execute(insert_analysis, {"project": project, "type": "ai_review"})
            connection.execute(insert_event, {"user": user, "type": "ai.explained"})
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert_analysis, {"project": project, "type": "ai_made_up"})

        command.downgrade(config, "4814067a0efe")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM analyses")) == 0
            assert connection.scalar(text("SELECT count(*) FROM activity_events")) == 0
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert_analysis, {"project": project, "type": "ai_review"})
    finally:
        command.upgrade(config, "head")
