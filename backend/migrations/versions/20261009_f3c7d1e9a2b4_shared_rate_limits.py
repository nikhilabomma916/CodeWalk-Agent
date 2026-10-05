"""shared rate limits across API instances (Module 21)

``rate_limit_events`` holds one row per counted attempt (hashed key, time), so login, registration,
AI, agent, retrieval and import limits apply across every API process instead of per process.

Additive only: a new table. Downgrade drops it (the limits then fall back to per-process counters).

Revision ID: f3c7d1e9a2b4
Revises: e8b2f4a6c1d9
Create Date: 2026-10-09 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c7d1e9a2b4"
down_revision: str | Sequence[str] | None = "e8b2f4a6c1d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_limit_events")),
    )
    op.create_index(
        "ix_rate_limit_events_key_hash_occurred_at", "rate_limit_events", ["key_hash", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_events_key_hash_occurred_at", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
