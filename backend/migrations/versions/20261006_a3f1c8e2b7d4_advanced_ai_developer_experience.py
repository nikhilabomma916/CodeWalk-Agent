"""agent modes, findings, usage, proposal groups, new-file proposals, project memory (Module 17)

- ``agent_runs``: ``mode`` (the workflow chosen: assist, review, tests, ...), ``findings`` (review
  findings recorded by the agent, validated against the project) and ``usage`` (provider calls, tokens,
  context size). Existing runs get ``assist``, ``[]`` and ``{}``.
- ``agent_actions``: ``kind`` (``code_change`` or ``create_file``), ``group_id`` (proposals created by one
  tool call are decided together), ``confidence`` and ``risk``. ``file_id`` becomes nullable: a
  ``create_file`` proposal has no file yet. Existing proposals keep their file and become ``code_change``.
- ``project_memories``: short notes the developer saves for the AI about one project.

Additive only: no existing row is changed beyond the new columns' defaults. Downgrade deletes
``create_file`` proposals (they cannot satisfy the restored NOT NULL) and drops what was added.

Revision ID: a3f1c8e2b7d4
Revises: 9c4d2b7a1e83
Create Date: 2026-10-06 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3f1c8e2b7d4"
down_revision: str | Sequence[str] | None = "9c4d2b7a1e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_KINDS = ("convention", "decision", "terminology", "constraint", "preference")


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("mode", sa.String(length=32), server_default="assist", nullable=False)
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "usage",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "agent_actions", sa.Column("kind", sa.String(length=32), server_default="code_change", nullable=False)
    )
    op.add_column("agent_actions", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.add_column("agent_actions", sa.Column("confidence", sa.String(length=16), nullable=True))
    op.add_column("agent_actions", sa.Column("risk", sa.String(length=16), nullable=True))
    op.alter_column("agent_actions", "file_id", existing_type=sa.Uuid(), nullable=True)
    op.create_index("ix_agent_actions_group_id", "agent_actions", ["group_id"])

    op.create_table(
        "project_memories",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*MEMORY_KINDS, name="memory_kind", native_enum=False, create_constraint=False, length=32),
            nullable=False,
        ),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_memories_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_project_memories_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_memories")),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in MEMORY_KINDS) + ")",
            name=op.f("ck_project_memories_memory_kind"),
        ),
    )
    op.create_index(
        "ix_project_memories_project_id_created_at", "project_memories", ["project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_project_memories_project_id_created_at", table_name="project_memories")
    op.drop_table("project_memories")
    op.execute("DELETE FROM agent_actions WHERE file_id IS NULL")
    op.drop_index("ix_agent_actions_group_id", table_name="agent_actions")
    op.alter_column("agent_actions", "file_id", existing_type=sa.Uuid(), nullable=False)
    for column in ("risk", "confidence", "group_id", "kind"):
        op.drop_column("agent_actions", column)
    for column in ("usage", "findings", "mode"):
        op.drop_column("agent_runs", column)
