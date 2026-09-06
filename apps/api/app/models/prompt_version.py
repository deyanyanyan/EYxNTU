"""Versioned, activatable prompt sets.

One row = one named set of prompt templates for a given `task`
(e.g. "critique", "plan", "slides", "quiz"). Exactly one row per task may be
active. Templates use `{placeholder}` substitution (see core/prompts/service.py).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromptVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "prompt_versions"

    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Named sub-prompts for the task, e.g. {"grounding": "...", "coherence": "...", "pedagogy": "...", "summary": "..."}
    templates: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    last_activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_id], lazy="joined")
    last_activated_by = relationship("User", foreign_keys=[last_activated_by_id], lazy="joined")
