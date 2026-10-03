"""users, login sessions, project ownership, file versions, activity history

Projects now belong to a user. Projects created before accounts existed have no
owner and cannot be assigned one automatically (no users exist yet), so the
upgrade stops if any are present. Re-run with ``-x delete_unowned_projects=true``
to delete them (with their files and analyses) and continue.

Downgrade drops users, sessions, ownership, version history, and the activity history.

Revision ID: 4814067a0efe
Revises: 32a816011f6f
Create Date: 2026-10-01 20:11:11.347294

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4814067a0efe"
down_revision: str | Sequence[str] | None = "32a816011f6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _remove_unowned_projects() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM projects"))
    if not count:
        return
    if context.get_x_argument(as_dictionary=True).get("delete_unowned_projects") != "true":
        raise RuntimeError(
            f"{count} project(s) were created before user accounts existed and have no owner. "
            "Re-run with `alembic -x delete_unowned_projects=true upgrade head` to delete them."
        )
    op.execute("DELETE FROM projects")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_index(op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "file_versions",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "create",
                "edit",
                "restore",
                "scan",
                name="file_version_source",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "source IN ('create', 'edit', 'restore', 'scan')",
            name=op.f("ck_file_versions_file_version_source"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_file_versions_author_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_file_versions_file_id_files"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_versions")),
        sa.UniqueConstraint("file_id", "version", name="uq_file_versions_file_id_version"),
    )

    _remove_unowned_projects()
    op.add_column("projects", sa.Column("owner_id", sa.Uuid(), nullable=False))
    op.drop_index("uq_projects_lower_name", table_name="projects")
    op.create_index(
        "uq_projects_owner_id_lower_name",
        "projects",
        ["owner_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_foreign_key(
        op.f("fk_projects_owner_id_users"), "projects", "users", ["owner_id"], ["id"], ondelete="CASCADE"
    )

    op.create_table(
        "activity_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "project.created",
                "project.updated",
                "project.deleted",
                "project.analyzed",
                "file.created",
                "file.updated",
                "file.restored",
                "file.deleted",
                "file.analyzed",
                name="activity_type",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("project_name", sa.String(length=100), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('project.created', 'project.updated', 'project.deleted', 'project.analyzed', "
            "'file.created', 'file.updated', 'file.restored', 'file.deleted', 'file.analyzed')",
            name=op.f("ck_activity_events_activity_type"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_activity_events_analysis_id_analyses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_activity_events_file_id_files"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_activity_events_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_activity_events_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_events")),
    )
    op.create_index(
        "ix_activity_events_user_id_created_at", "activity_events", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_activity_events_project_id_created_at",
        "activity_events",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_activity_events_project_id_created_at", table_name="activity_events")
    op.drop_index("ix_activity_events_user_id_created_at", table_name="activity_events")
    op.drop_table("activity_events")
    op.drop_constraint(op.f("fk_projects_owner_id_users"), "projects", type_="foreignkey")
    op.drop_index("uq_projects_owner_id_lower_name", table_name="projects")
    # Names were unique per user; they must be globally unique again.
    op.execute(
        """
        UPDATE projects AS p SET name = left(p.name, 90) || ' (' || left(p.id::text, 8) || ')'
        WHERE EXISTS (
            SELECT 1 FROM projects AS q WHERE lower(q.name) = lower(p.name) AND q.id < p.id
        )
        """
    )
    op.create_index("uq_projects_lower_name", "projects", [sa.literal_column("lower(name)")], unique=True)
    op.drop_column("projects", "owner_id")
    op.drop_table("file_versions")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_expires_at"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
