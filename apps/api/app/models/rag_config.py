from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RagConfig(Base, TimestampMixin):
    """Key/value store for retrieval state (embedding model in use, last run, chunk counts).

    Persisting the embedding model name guards against querying an index built
    with a different model after an env change: the retriever reads it back.
    """

    __tablename__ = "rag_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
