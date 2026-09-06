from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A course-generation workspace: sources in, course package out."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # Course brief captured up-front (feeds the planner).
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    learning_goals: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner = relationship("User", lazy="joined")
    sources = relationship("Source", back_populates="project", cascade="all, delete-orphan")
