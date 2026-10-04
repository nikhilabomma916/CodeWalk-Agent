"""pgvector extension and code_chunks (semantic retrieval, Module 10)

Enables the ``vector`` extension (``CREATE EXTENSION IF NOT EXISTS vector``; needs a
PostgreSQL server with pgvector installed, e.g. the pgvector/pgvector:pg17-bookworm
image) and adds ``code_chunks``: embedded pieces of project files, owned through
``projects``/``files`` (deleted with them). An HNSW index serves cosine-distance search.

Downgrade drops ``code_chunks`` but keeps the extension: other objects may use it,
and it holds no data of its own.

Revision ID: 5c1e9a7b3d20
Revises: aa335eec9810
Create Date: 2026-10-03 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.vector import Vector

# revision identifiers, used by Alembic.
revision: str = "5c1e9a7b3d20"
down_revision: str | Sequence[str] | None = "aa335eec9810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1024  # frozen here: changing the width is a new migration


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "code_chunks",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("symbol_kind", sa.String(length=32), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_code_chunks_file_id_files"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_code_chunks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_chunks")),
        sa.UniqueConstraint(
            "file_id", "embedding_model", "chunk_index", name="uq_code_chunks_file_model_index"
        ),
    )
    op.create_index(
        "ix_code_chunks_project_id_embedding_model", "code_chunks", ["project_id", "embedding_model"]
    )
    op.create_index("ix_code_chunks_file_id_chunk_hash", "code_chunks", ["file_id", "chunk_hash"])
    op.create_index(
        "ix_code_chunks_embedding_hnsw",
        "code_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_code_chunks_embedding_hnsw", table_name="code_chunks")
    op.drop_index("ix_code_chunks_file_id_chunk_hash", table_name="code_chunks")
    op.drop_index("ix_code_chunks_project_id_embedding_model", table_name="code_chunks")
    op.drop_table("code_chunks")
