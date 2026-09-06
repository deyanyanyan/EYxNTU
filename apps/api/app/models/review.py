from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Review(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Human review decision or comment on a plan or asset."""

    __tablename__ = "reviews"

    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # plan | asset
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)  # approve | reject | comment
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # anchor inside asset content

    reviewer = relationship("User", lazy="joined")
