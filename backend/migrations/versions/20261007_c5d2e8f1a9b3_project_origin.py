"""project origin: workspace or uploaded from a local folder (Module 18)

``projects.origin`` says where a project came from: ``workspace`` (created in Coding/Projects, the
default for every existing project) or ``upload`` (a folder uploaded from the developer's computer).
Uploaded projects are listed only in the Uploads area and are analyzed read-only.

Additive only: existing rows get ``workspace``; no row is otherwise changed. Downgrade drops the column.

Revision ID: c5d2e8f1a9b3
Revises: a3f1c8e2b7d4
Create Date: 2026-10-07 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d2e8f1a9b3"
down_revision: str | Sequence[str] | None = "a3f1c8e2b7d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORIGINS = ("workspace", "upload")


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "origin",
            sa.Enum(*ORIGINS, name="project_origin", native_enum=False, create_constraint=False, length=32),
            server_default="workspace",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_projects_project_origin"),
        "projects",
        "origin IN (" + ", ".join(f"'{o}'" for o in ORIGINS) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_projects_project_origin"), "projects", type_="check")
    op.drop_column("projects", "origin")
