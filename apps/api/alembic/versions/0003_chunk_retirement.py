"""chunk retirement: re-ingesting a source no longer deletes the citations on its course

Revision ID: 0003_chunk_retirement
Revises: 0002_course_revisions
Create Date: 2026-11-18

- chunks.retired_at: set on a source's previous chunks when it is re-ingested. Chunks whose
  text is unchanged are swapped for the new ones everywhere the course refers to them;
  changed ones the course still cites are kept, retired, and excluded from retrieval.
  See app/core/rag/carry_over.py.
"""
import sqlalchemy as sa

from alembic import op

revision = "0003_chunk_retirement"
down_revision = "0002_course_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM chunks WHERE retired_at IS NOT NULL")
    op.drop_column("chunks", "retired_at")
