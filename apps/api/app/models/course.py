from __future__ import annotations

import enum

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlanStatus(enum.StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class CoursePlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Objectives + syllabus for a project. Must be APPROVED before asset generation."""

    __tablename__ = "course_plans"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    learning_objectives: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # [{text, bloom_level, source_chunk_ids}]
    status: Mapped[str] = mapped_column(String(32), default=PlanStatus.DRAFT.value, nullable=False)
    coverage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {source_id: fraction_covered}
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # why this version exists: {instructions, intents} or {edited_from, change}

    modules = relationship("Module", back_populates="plan", cascade="all, delete-orphan", order_by="Module.position")


class Module(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "modules"

    plan_id: Mapped[str] = mapped_column(ForeignKey("course_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan = relationship("CoursePlan", back_populates="modules")
    lessons = relationship("Lesson", back_populates="module", cascade="all, delete-orphan", order_by="Lesson.position")


class Lesson(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "lessons"

    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    objective_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # planner's coverage map
    origin_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # the lesson an outline version copied this from

    module = relationship("Module", back_populates="lessons")
    assets = relationship("Asset", back_populates="lesson", cascade="all, delete-orphan")
