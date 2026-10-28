"""course revisions: kept asset versions, lesson lineage, outline version notes

Revision ID: 0002_course_revisions
Revises: 0001_initial
Create Date: 2026-10-28

- assets.superseded_at: a regenerated, fixed or edited asset keeps its earlier
  versions instead of deleting them, so any version can be restored.
- lessons.origin_id: the lesson an outline version copied this one from, so content
  carries over and versions can be compared lesson by lesson.
- course_plans.meta: why a version exists (instructions, or the edit that created it).
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_course_revisions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("lessons", sa.Column("origin_id", sa.String(36), nullable=True))
    op.add_column("course_plans", sa.Column("meta", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("course_plans", "meta")
    op.drop_column("lessons", "origin_id")
    op.drop_column("assets", "superseded_at")
