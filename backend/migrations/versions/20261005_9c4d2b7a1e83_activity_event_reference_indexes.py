"""indexes for activity_events.file_id and activity_events.analysis_id (Module 16)

Both columns reference rows that are deleted during normal use, with ``ON DELETE SET NULL``:
every file save beyond the per-file analysis history prunes the oldest analysis, and deleting a
file (or a folder rescan removing files) deletes file rows. For each deleted row PostgreSQL runs
``UPDATE activity_events SET ... = NULL WHERE <column> = $1``; without an index that is a full scan
of the activity history, which only grows. Partial indexes (``IS NOT NULL``) cover exactly the
rows such an update can touch and stay small.

The indexes are built ``CONCURRENTLY`` (outside the migration transaction), so an existing
installation keeps accepting writes while they are created. No data is changed. Downgrade drops
the two indexes.

Revision ID: 9c4d2b7a1e83
Revises: 7b3e1c9d4f62
Create Date: 2026-10-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c4d2b7a1e83"
down_revision: str | Sequence[str] | None = "7b3e1c9d4f62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_activity_events_file_id", "file_id"),
    ("ix_activity_events_analysis_id", "analysis_id"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, column in INDEXES:
            # An interrupted concurrent build leaves an invalid index behind: rebuild it.
            invalid = op.get_bind().execute(
                sa.text(
                    "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE c.relname = :name AND NOT i.indisvalid"
                ),
                {"name": name},
            )
            if invalid.first() is not None:
                op.drop_index(name, table_name="activity_events", postgresql_concurrently=True)
            op.create_index(
                name,
                "activity_events",
                [column],
                postgresql_where=sa.text(f"{column} IS NOT NULL"),
                postgresql_concurrently=True,
                if_not_exists=True,
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in INDEXES:
            op.drop_index(name, table_name="activity_events", postgresql_concurrently=True, if_exists=True)
