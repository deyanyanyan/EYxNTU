from __future__ import annotations

import enum

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AssetKind(enum.StrEnum):
    SLIDES = "slides"          # structured slide JSON -> PPTX/HTML
    NOTES = "notes"            # speaker notes
    QUIZ = "quiz"              # questions + answer key
    TUTORIAL = "tutorial"      # worked example / exercise
    SCRIPT = "script"          # narration script
    AUDIO = "audio"            # TTS output
    VIDEO = "video"            # rendered lesson video
    SCORM = "scorm"            # packaged course (project-level, lesson_id null)


class ApprovalState(enum.StrEnum):
    GENERATED = "generated"
    EDITED = "edited"
    APPROVED = "approved"
    REJECTED = "rejected"


class Asset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A generated learning asset. `content` is the structured JSON the editor
    works on; `file_path` is the rendered artefact (PPTX, MP4, ZIP) if any."""

    __tablename__ = "assets"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    approval: Mapped[str] = mapped_column(String(32), default=ApprovalState.GENERATED.value, nullable=False)

    # Critique scores (0-5) produced by the critique agent.
    grounding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    coherence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pedagogy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    critique: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    generated_with_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_versions.id"), nullable=True)

    lesson = relationship("Lesson", back_populates="assets")
    citations = relationship("Citation", back_populates="asset", cascade="all, delete-orphan")


class Citation(Base, UUIDPrimaryKeyMixin):
    """Content map entry: a block inside an asset traced back to a source chunk."""

    __tablename__ = "citations"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    block_id: Mapped[str] = mapped_column(String(128), nullable=False)  # id of the slide/question/paragraph inside content
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)  # supporting span, verbatim

    asset = relationship("Asset", back_populates="citations")
    chunk = relationship("Chunk", lazy="joined")
