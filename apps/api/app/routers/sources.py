"""Upload sources into a project and trigger ingestion jobs."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.deps import require_instructor
from app.core.auth.permissions import assert_project_access
from app.core.jobs import service as jobs
from app.core.rag.parser import SUPPORTED
from app.db.session import get_db
from app.models.job import JobKind
from app.models.project import Project
from app.models.source import Source, SourceStatus
from app.models.user import User
from app.schemas.job import JobOut
from app.schemas.project import SourceOut

router = APIRouter(prefix="/projects/{project_id}/sources", tags=["sources"])


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
    jobs.enqueue(db, JobKind.INGEST_SOURCE, {"source_id": src.id}, project_id=project_id, started_by=actor.id, supersede_key="source_id")
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
    return jobs.enqueue(db, JobKind.INGEST_SOURCE, {"source_id": src.id}, project_id=project_id, started_by=actor.id, supersede_key="source_id")


@router.delete("/{source_id}", status_code=204)
def delete_source(project_id: str, source_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    src = db.get(Source, source_id)
    if not src or src.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source not found")
    (settings.data_dir / src.storage_path).unlink(missing_ok=True)
    db.delete(src)
    db.commit()
