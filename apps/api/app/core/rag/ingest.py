"""Source ingestion pipeline: parse -> chunk -> embed -> store.

Called by the worker for `ingest_source` jobs. Reports progress and honours
cancellation through the job service.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.core.jobs import service as jobs
from app.core.llm.embeddings import embed_texts
from app.core.rag import rendition
from app.core.rag.chunker import chunk_elements
from app.core.rag.parser import parse_document
from app.models.chunk import Chunk
from app.models.rag_config import RagConfig
from app.models.source import Source, SourceStatus

log = logging.getLogger(__name__)


def ingest_source(db: Session, source_id: str, job_id: str | None = None) -> dict:
    src = db.get(Source, source_id)
    if not src:
        raise ValueError(f"source {source_id} not found")
    path = settings.data_dir / src.storage_path

    try:
        src.status = SourceStatus.PARSING.value
        db.commit()
        if job_id:
            jobs.progress(db, job_id, message=f"Parsing {src.filename}")

        elements, structure = parse_document(Path(path))
        src.structure = structure
        src.page_count = structure.get("pages")
        src.status = SourceStatus.PARSED.value
        db.commit()

        if Path(src.storage_path).suffix.lower() in rendition.RENDERED:
            if job_id:
                jobs.progress(db, job_id, message=f"Rendering {src.filename} for viewing")
            try:
                rendition.render_pdf(Path(path), settings.data_dir / rendition.rendition_path(src.storage_path))
            except Exception as exc:  # the viewer falls back to the original file
                log.warning("no viewable rendition for %s: %s", src.filename, exc)

        drafts = chunk_elements(elements)
        if not drafts:
            raise ValueError("no text could be extracted")

        # replace any previous chunks for this source
        db.execute(delete(Chunk).where(Chunk.source_id == src.id))
        src.status = SourceStatus.EMBEDDING.value
        db.commit()
        if job_id:
            jobs.progress(db, job_id, current=0, total=len(drafts), message=f"Embedding {len(drafts)} chunks")

        bs = settings.embedding_batch_size
        for i in range(0, len(drafts), bs):
            if job_id and jobs.is_cancelled(db, job_id):
                src.status = SourceStatus.FAILED.value
                src.error = "cancelled"
                db.commit()
                return {"cancelled": True}
            batch = drafts[i : i + bs]
            vecs = embed_texts([d.text for d in batch])
            for d, v in zip(batch, vecs, strict=True):
                db.add(
                    Chunk(
                        source_id=src.id,
                        project_id=src.project_id,
                        chunk_index=d.chunk_index,
                        text=d.text,
                        embedding=v,
                        heading_path=d.heading_path or None,
                        page_start=d.page_start,
                        page_end=d.page_end,
                        element_type=d.element_type,
                        meta=d.meta or None,
                    )
                )
            db.commit()
            if job_id:
                jobs.progress(db, job_id, current=min(i + bs, len(drafts)))

        src.chunk_count = len(drafts)
        src.status = SourceStatus.READY.value
        src.error = None
        _set_config(db, "embedding_model", settings.embedding_model)
        _set_config(db, "last_ingest_at", datetime.now(UTC).isoformat())
        db.commit()
        return {"chunks": len(drafts), "parser": structure.get("parser")}
    except Exception as exc:
        db.rollback()
        src = db.get(Source, source_id)
        if src:
            src.status = SourceStatus.FAILED.value
            src.error = str(exc)[:2000]
            db.commit()
        raise


def _set_config(db: Session, key: str, value: str) -> None:
    row = db.get(RagConfig, key)
    if row:
        row.value = value
    else:
        db.add(RagConfig(key=key, value=value))
