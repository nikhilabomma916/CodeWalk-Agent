"""GitHub integration: connected accounts and imported project sources (Module 20)

- ``github_connections``: one connected GitHub account per user; the OAuth token only encrypted.
- ``project_sources``: the repository, branch and commit an imported project came from.
- activity type ``github.imported``.

Additive only: no existing table or row is changed. Downgrade drops the two new tables (and with them
the stored connections) and removes ``github.imported`` activity events before restoring the check.

Revision ID: e8b2f4a6c1d9
Revises: c5d2e8f1a9b3
Create Date: 2026-10-08 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b2f4a6c1d9"
down_revision: str | Sequence[str] | None = "c5d2e8f1a9b3"
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
    "agent.run",
    "agent.action_applied",
    "agent.action_rejected",
]
GITHUB_EVENT_TYPES = ["github.imported"]


def _replace_event_check(event_types: list[str]) -> None:
    op.drop_constraint(op.f("ck_activity_events_activity_type"), "activity_events", type_="check")
    op.create_check_constraint(
        op.f("ck_activity_events_activity_type"),
        "activity_events",
        "event_type IN (" + ", ".join(f"'{value}'" for value in event_types) + ")",
    )


def upgrade() -> None:
    op.create_table(
        "github_connections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.String(length=39), nullable=False),
        sa.Column("scopes", sa.String(length=200), server_default="", nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_github_connections_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_github_connections")),
        sa.UniqueConstraint("user_id", name=op.f("uq_github_connections_user_id")),
    )
    op.create_table(
        "project_sources",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), server_default="github", nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(length=140), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("is_private", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("files_imported", sa.Integer(), server_default="0", nullable=False),
        sa.Column("files_skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_sources_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_sources")),
        sa.UniqueConstraint("project_id", name=op.f("uq_project_sources_project_id")),
    )
    op.create_index("ix_project_sources_repository_id_branch", "project_sources", ["repository_id", "branch"])
    _replace_event_check(EVENT_TYPES + GITHUB_EVENT_TYPES)


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM activity_events WHERE event_type IN :types").bindparams(
            sa.bindparam("types", expanding=True)
        ),
        {"types": GITHUB_EVENT_TYPES},
    )
    _replace_event_check(EVENT_TYPES)
    op.drop_index("ix_project_sources_repository_id_branch", table_name="project_sources")
    op.drop_table("project_sources")
    op.drop_table("github_connections")
