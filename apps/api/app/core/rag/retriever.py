"""pgvector retrieval scoped to a project.

Cosine distance operator `<=>` on the HNSW index; similarity = 1 - distance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.llm.embeddings import embed_query
from app.models.chunk import Chunk
from app.models.rag_config import RagConfig
from app.models.source import Source

log = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_id: str
    source_name: str
    text: str
    heading_path: str | None
    page_start: int | None
    page_end: int | None
    similarity: float


def retrieve(
    db: Session,
    project_id: str,
    query: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
    source_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    top_k = top_k or settings.rag_top_k
    threshold = settings.rag_similarity_threshold if threshold is None else threshold

    _assert_index_model(db)
    qvec = embed_query(query)
    distance = Chunk.embedding.cosine_distance(qvec).label("distance")

    stmt = (
        select(Chunk, Source.filename, distance)
        .join(Source, Source.id == Chunk.source_id)
        .where(Chunk.project_id == project_id)
        .order_by(distance)
        .limit(top_k)
    )
    if source_ids:
        stmt = stmt.where(Chunk.source_id.in_(source_ids))

    out: list[RetrievedChunk] = []
    for chunk, fname, dist in db.execute(stmt):
        sim = 1.0 - float(dist)
        if sim < threshold:
            continue
        out.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                source_id=chunk.source_id,
                source_name=fname,
                text=chunk.text,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                similarity=round(sim, 4),
            )
        )
    log.info("retrieved %s chunks for project %s (top=%s)", len(out), project_id, out[0].similarity if out else None)
    return out


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Numbered references the LLM can cite as [1], [2] ... ; ids map back via `citation_map`."""
    parts = []
    for i, c in enumerate(chunks, 1):
        loc = f"{c.source_name}"
        if c.heading_path:
            loc += f" › {c.heading_path}"
        if c.page_start:
            loc += f" (p.{c.page_start}{'-' + str(c.page_end) if c.page_end and c.page_end != c.page_start else ''})"
        parts.append(f"[{i}] {loc}\n{c.text}")
    return "\n\n".join(parts)


def citation_map(chunks: list[RetrievedChunk]) -> dict[int, str]:
    return {i: c.chunk_id for i, c in enumerate(chunks, 1)}


def _assert_index_model(db: Session) -> None:
    row = db.get(RagConfig, "embedding_model")
    if row and row.value and row.value != settings.embedding_model:
        raise RuntimeError(
            f"Index was built with {row.value} but EMBEDDING_MODEL={settings.embedding_model}. Re-embed all sources."
        )
