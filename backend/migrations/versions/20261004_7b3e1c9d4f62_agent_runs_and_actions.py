"""agent runs, proposed actions, and agent activity events (Module 11)

Adds ``agent_runs`` (one row per agent request: status, answer, progress events and
tool-call metadata; no hidden reasoning) and ``agent_actions`` (changes the agent
proposed to a stored file, applied only by explicit approval). Both are owned
through ``users``/``projects`` and deleted with them. Widens the
``activity_events.event_type`` CHECK constraint with ``agent.run``,
``agent.action_applied`` and ``agent.action_rejected``. No existing table or row
is changed.

Downgrade deletes agent history events and drops the two tables.

Revision ID: 7b3e1c9d4f62
Revises: 5c1e9a7b3d20
Create Date: 2026-10-04 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7b3e1c9d4f62"
down_revision: str | Sequence[str] | None = "5c1e9a7b3d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPES = [
    "project.created",
    "project.updated",
    "project.deleted",
    "project.analyzed",
    "file.created",
    "file.updated",
    "file.restored",
    "file.deleted",
    "file.analyzed",
    "ai.analyzed",
    "ai.explained",
    "ai.fix_suggested",
]
AGENT_EVENT_TYPES = ["agent.run", "agent.action_applied", "agent.action_rejected"]
RUN_STATUSES = ["completed", "limit_reached", "failed"]
ACTION_STATUSES = ["pending", "applied", "rejected", "stale"]


def _values(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_event_check(event_types: list[str]) -> None:
    op.drop_constraint(op.f("ck_activity_events_activity_type"), "activity_events", type_="check")
    op.create_check_constraint(
        op.f("ck_activity_events_activity_type"), "activity_events", f"event_type IN ({_values(event_types)})"
    )


def _status(name: str, values: list[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False, length=32)


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", _status("agent_run_status", RUN_STATUSES), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"status IN ({_values(RUN_STATUSES)})", name=op.f("ck_agent_runs_agent_run_status")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_agent_runs_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_runs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index("ix_agent_runs_user_id_created_at", "agent_runs", ["user_id", "created_at"])
    op.create_index("ix_agent_runs_project_id_created_at", "agent_runs", ["project_id", "created_at"])

    op.create_table(
        "agent_actions",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("status", _status("agent_action_status", ACTION_STATUSES), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("base_content_hash", sa.String(length=64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            f"status IN ({_values(ACTION_STATUSES)})", name=op.f("ck_agent_actions_agent_action_status")
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_agent_actions_file_id_files"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_agent_actions_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_runs.id"], name=op.f("fk_agent_actions_run_id_agent_runs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_actions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_actions")),
    )
    op.create_index("ix_agent_actions_run_id", "agent_actions", ["run_id"])
    op.create_index("ix_agent_actions_user_id_status", "agent_actions", ["user_id", "status"])
    op.create_index("ix_agent_actions_file_id", "agent_actions", ["file_id"])

    _replace_event_check(EVENT_TYPES + AGENT_EVENT_TYPES)


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM activity_events WHERE event_type IN :types").bindparams(
            sa.bindparam("types", expanding=True)
        ),
        {"types": AGENT_EVENT_TYPES},
    )
    _replace_event_check(EVENT_TYPES)
    op.drop_index("ix_agent_actions_file_id", table_name="agent_actions")
    op.drop_index("ix_agent_actions_user_id_status", table_name="agent_actions")
    op.drop_index("ix_agent_actions_run_id", table_name="agent_actions")
    op.drop_table("agent_actions")
    op.drop_index("ix_agent_runs_project_id_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id_created_at", table_name="agent_runs")
    op.drop_table("agent_runs")
