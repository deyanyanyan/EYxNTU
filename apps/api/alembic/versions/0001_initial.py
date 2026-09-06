"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-06
"""
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from app.config import settings

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DIM = settings.embedding_dim


def _ts():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="learner"),
        sa.Column("org_unit", sa.String(255)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts(),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_audience", sa.Text),
        sa.Column("duration_minutes", sa.Integer),
        sa.Column("learning_goals", sa.Text),
        *_ts(),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    op.create_table(
        "sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("error", sa.Text),
        sa.Column("structure", postgresql.JSONB),
        sa.Column("page_count", sa.Integer),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        *_ts(),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("heading_path", sa.String(1024)),
        sa.Column("page_start", sa.Integer),
        sa.Column("page_end", sa.Integer),
        sa.Column("element_type", sa.String(32)),
        sa.Column("meta", postgresql.JSONB),
        *_ts(),
    )
    op.create_index("ix_chunks_source_id", "chunks", ["source_id"])
    op.create_index("ix_chunks_project_id", "chunks", ["project_id"])
    op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)")

    op.create_table(
        "course_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("learning_objectives", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("coverage", postgresql.JSONB),
        *_ts(),
    )
    op.create_index("ix_course_plans_project_id", "course_plans", ["project_id"])

    op.create_table(
        "modules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("course_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text),
        *_ts(),
    )
    op.create_index("ix_modules_plan_id", "modules", ["plan_id"])

    op.create_table(
        "lessons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("module_id", sa.String(36), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("objective_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("estimated_minutes", sa.Integer),
        sa.Column("source_chunk_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        *_ts(),
    )
    op.create_index("ix_lessons_module_id", "lessons", ["module_id"])

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("system_prompt", sa.Text),
        sa.Column("templates", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("last_activated_at", sa.DateTime(timezone=True)),
        sa.Column("last_activated_by_id", sa.String(36), sa.ForeignKey("users.id")),
        *_ts(),
    )
    op.create_index("ix_prompt_versions_task", "prompt_versions", ["task"])

    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(36), sa.ForeignKey("lessons.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("content", postgresql.JSONB),
        sa.Column("file_path", sa.String(1024)),
        sa.Column("approval", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("grounding_score", sa.Float),
        sa.Column("coherence_score", sa.Float),
        sa.Column("pedagogy_score", sa.Float),
        sa.Column("critique", postgresql.JSONB),
        sa.Column("generated_with_model", sa.String(255)),
        sa.Column("prompt_version_id", sa.String(36), sa.ForeignKey("prompt_versions.id")),
        *_ts(),
    )
    op.create_index("ix_assets_project_id", "assets", ["project_id"])
    op.create_index("ix_assets_lesson_id", "assets", ["lesson_id"])

    op.create_table(
        "citations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_id", sa.String(128), nullable=False),
        sa.Column("chunk_id", sa.String(36), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("similarity", sa.Float),
        sa.Column("quote", sa.Text),
    )
    op.create_index("ix_citations_asset_id", "citations", ["asset_id"])
    op.create_index("ix_citations_chunk_id", "citations", ["chunk_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB),
        sa.Column("progress_current", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("message", sa.Text),
        sa.Column("error_type", sa.String(128)),
        sa.Column("error_message", sa.Text),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("started_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(128)),
        *_ts(),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])

    op.create_table(
        "rag_config",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text),
        *_ts(),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(32)),
        sa.Column("comment", sa.Text),
        sa.Column("block_id", sa.String(128)),
        *_ts(),
    )
    op.create_index("ix_reviews_target_id", "reviews", ["target_id"])


def downgrade() -> None:
    for t in ["reviews", "rag_config", "jobs", "citations", "assets", "prompt_versions", "lessons", "modules", "course_plans", "chunks", "sources", "projects", "users"]:
        op.drop_table(t)
