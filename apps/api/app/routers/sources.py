"""Upload sources into a project and trigger ingestion jobs."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.deps import require_instructor
from app.core.auth.permissions import assert_project_access
from app.core.jobs import service as jobs
from app.core.rag import rendition
from app.core.rag.parser import SUPPORTED
from app.db.session import get_db
from app.models.asset import Asset, Citation
from app.models.chunk import Chunk
from app.models.course import CoursePlan, Lesson, Module
from app.models.job import JobKind
from app.models.project import Project
from app.models.source import Source, SourceStatus
from app.models.user import User
from app.schemas.job import JobOut
from app.schemas.project import LessonRefOut, SourceOut, SourceUsageOut

router = APIRouter(prefix="/projects/{project_id}/sources", tags=["sources"])
_NOSNIFF = {"X-Content-Type-Options": "nosniff"}


def _project(db: Session, actor: User, project_id: str, write: bool = True) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    assert_project_access(actor, p, write=write)
    return p


@router.post("", response_model=SourceOut, status_code=201)
async def upload_source(project_id: str, file: UploadFile = File(...), actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(status_code=415, detail=f"Unsupported type {ext}. Allowed: {sorted(SUPPORTED)}")

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or "upload").name)[:200]
    rel = Path("uploads") / project_id / f"{uuid.uuid4().hex[:8]}_{safe}"
    dest = settings.data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb} MB")
            out.write(chunk)

    src = Source(project_id=project_id, filename=safe, content_type=file.content_type or "application/octet-stream", size_bytes=size, storage_path=str(rel).replace("\\", "/"), status=SourceStatus.UPLOADED.value)
    db.add(src)
    db.commit()
    db.refresh(src)
    jobs.enqueue(db, JobKind.INGEST_SOURCE, {"source_id": src.id, "filename": src.filename}, project_id=project_id, started_by=actor.id, supersede_key="source_id")
    return src


@router.get("", response_model=list[SourceOut])
def list_sources(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    p = _project(db, actor, project_id, write=False)
    return sorted(p.sources, key=lambda s: s.created_at, reverse=True)


@router.post("/{source_id}/reingest", response_model=JobOut, status_code=202)
def reingest(project_id: str, source_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    src = db.get(Source, source_id)
    if not src or src.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return jobs.enqueue(db, JobKind.INGEST_SOURCE, {"source_id": src.id, "filename": src.filename}, project_id=project_id, started_by=actor.id, supersede_key="source_id")


@router.delete("/{source_id}", status_code=204)
def delete_source(project_id: str, source_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    src = db.get(Source, source_id)
    if not src or src.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source not found")
    (settings.data_dir / src.storage_path).unlink(missing_ok=True)
    (settings.data_dir / rendition.rendition_path(src.storage_path)).unlink(missing_ok=True)
    db.delete(src)
    db.commit()


def _stored(db: Session, actor: User, project_id: str, source_id: str) -> Source:
    _project(db, actor, project_id, write=False)
    src = db.get(Source, source_id)
    if not src or src.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


def _file(rel: str) -> Path:
    root = settings.data_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=410, detail="This file is no longer on disk. Upload it again.")
    return path


@router.get("/{source_id}/usage", response_model=SourceUsageOut)
def source_usage(project_id: str, source_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Where the project's current course draws on this source, so a delete can say what it affects.

    A lesson uses the source when its slides or quiz cite one of the source's passages, or the
    planner assigned it one; the plan uses it when an objective or the coverage map does.
    """
    src = _stored(db, actor, project_id, source_id)
    plan = db.scalar(select(CoursePlan).where(CoursePlan.project_id == project_id).order_by(CoursePlan.version.desc()).limit(1))
    if plan is None:
        return SourceUsageOut(in_course=False, lessons=[])
    chunks = set(db.scalars(select(Chunk.id).where(Chunk.source_id == src.id)))
    cited = set(db.scalars(
        select(Asset.lesson_id).join(Citation, Citation.asset_id == Asset.id).where(Citation.chunk_id.in_(list(chunks)), Asset.superseded_at.is_(None))
    )) if chunks else set()
    lessons = db.scalars(select(Lesson).join(Module, Module.id == Lesson.module_id).where(Module.plan_id == plan.id).order_by(Module.position, Lesson.position))
    used = [lesson for lesson in lessons if lesson.id in cited or chunks & set(lesson.source_chunk_ids or [])]
    planned = src.id in (plan.coverage or {}) or any(chunks & set(o.get("source_chunk_ids") or []) for o in plan.learning_objectives or [])
    return SourceUsageOut(in_course=bool(used) or planned, lessons=[LessonRefOut(id=lesson.id, title=lesson.title) for lesson in used])


@router.get("/{source_id}/original")
def source_original(project_id: str, source_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """The file exactly as uploaded."""
    src = _stored(db, actor, project_id, source_id)
    return FileResponse(_file(src.storage_path), media_type="application/octet-stream", filename=src.filename, headers=_NOSNIFF)


@router.get("/{source_id}/view")
def source_view(project_id: str, source_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """What the source viewer shows: the PDF itself, Markdown or text as text, and the PDF
    rendition of a Word or PowerPoint file (app/core/rag/rendition.py). Types are fixed by
    extension, never taken from the upload, so a mislabelled file cannot render as HTML."""
    src = _stored(db, actor, project_id, source_id)
    kind = rendition.viewer_kind(src.storage_path)
    if kind is None:
        raise HTTPException(status_code=404, detail="No viewable copy of this file yet. Re-ingest it to render one.")
    ext = Path(src.storage_path).suffix.lower()
    rel = src.storage_path if ext in (".pdf", *rendition.TEXT) else rendition.rendition_path(src.storage_path)
    media_type = "application/pdf" if kind == "pdf" else "text/plain; charset=utf-8"
    return FileResponse(_file(rel), media_type=media_type, headers={**_NOSNIFF, "Content-Disposition": "inline"})
