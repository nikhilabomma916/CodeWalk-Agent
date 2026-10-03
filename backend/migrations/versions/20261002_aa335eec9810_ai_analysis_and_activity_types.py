"""AI analysis types and AI activity events

Adds the values ``ai_review``, ``ai_explanation``, ``ai_fix_suggestion`` to
``analyses.analysis_type`` and ``ai.analyzed``, ``ai.explained``,
``ai.fix_suggested`` to ``activity_events.event_type``. Both columns are
VARCHAR + CHECK, so only the CHECK constraints change; no new tables.

Downgrade deletes AI analyses and AI history events, then restores the
previous constraints.

Revision ID: aa335eec9810
Revises: 4814067a0efe
Create Date: 2026-10-02 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa335eec9810"
down_revision: str | Sequence[str] | None = "4814067a0efe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSIS_TYPES = ["code", "project_intelligence"]
AI_ANALYSIS_TYPES = ["ai_review", "ai_explanation", "ai_fix_suggestion"]
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
]
AI_EVENT_TYPES = ["ai.analyzed", "ai.explained", "ai.fix_suggested"]


def _values(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_checks(analysis_types: list[str], event_types: list[str]) -> None:
    op.drop_constraint(op.f("ck_analyses_analysis_type"), "analyses", type_="check")
    op.create_check_constraint(
        op.f("ck_analyses_analysis_type"), "analyses", f"analysis_type IN ({_values(analysis_types)})"
    )
    op.drop_constraint(op.f("ck_activity_events_activity_type"), "activity_events", type_="check")
    op.create_check_constraint(
        op.f("ck_activity_events_activity_type"), "activity_events", f"event_type IN ({_values(event_types)})"
    )


def upgrade() -> None:
    """Upgrade schema."""
    _replace_checks(ANALYSIS_TYPES + AI_ANALYSIS_TYPES, EVENT_TYPES + AI_EVENT_TYPES)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM activity_events WHERE event_type IN :types").bindparams(
            sa.bindparam("types", expanding=True)
        ),
        {"types": AI_EVENT_TYPES},
    )
    bind.execute(
        sa.text("DELETE FROM analyses WHERE analysis_type IN :types").bindparams(
            sa.bindparam("types", expanding=True)
        ),
        {"types": AI_ANALYSIS_TYPES},
    )
    _replace_checks(ANALYSIS_TYPES, EVENT_TYPES)
