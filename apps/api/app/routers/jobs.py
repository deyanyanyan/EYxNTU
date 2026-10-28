"""Job centre: list, cancel, and a Server-Sent-Events stream for live progress."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.deps import get_current_user, require_admin, require_instructor
from app.core.auth.security import decode_token
from app.core.jobs import service as jobs
from app.db.session import SessionLocal, get_db
from app.models.course import CoursePlan
from app.models.job import Job
from app.models.project import Project
from app.models.source import Source
from app.models.user import User
from app.schemas.job import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(project_id: str | None = None, recent_minutes: int = 30, _: User = Depends(require_instructor), db: Session = Depends(get_db)):
    rows = jobs.list_jobs(db, project_id=project_id, recent_minutes=recent_minutes)
    project_ids = {j.project_id for j in rows if j.project_id}
    source_ids = {j.payload.get("source_id") for j in rows if j.payload.get("source_id")}
    projects = dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).all()) if project_ids else {}
    sources = dict(db.execute(select(Source.id, Source.filename).where(Source.id.in_(source_ids))).all()) if source_ids else {}
    courses: dict[str, str] = {}
    for plan in db.scalars(select(CoursePlan).where(CoursePlan.project_id.in_(project_ids)).order_by(CoursePlan.version)) if project_ids else []:
        courses[plan.project_id] = plan.title  # ascending versions: the latest wins
    return [
        JobOut.model_validate(j).model_copy(update={
            "project_name": projects.get(j.project_id),
            "course_title": courses.get(j.project_id),
            # Jobs record the file name since 28 Oct 2026; older ones are looked up while the source exists.
            "source_name": j.payload.get("filename") or sources.get(j.payload.get("source_id")),
        })
        for j in rows
    ]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, _: User = Depends(require_instructor), db: Session = Depends(get_db)):
    job = jobs.request_cancel(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/finished", status_code=200)
def purge_finished(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"deleted": jobs.delete_finished(db)}


@router.get("/stream/{job_id}")
async def stream_job(job_id: str, token: str = Query(..., description="JWT; EventSource cannot set headers")):
    """SSE stream of a single job's progress until it finishes."""
    if not decode_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    async def gen():
        last = None
        while True:
            db = SessionLocal()
            try:
                job = db.get(Job, job_id)
                if not job:
                    yield "event: error\ndata: {\"detail\": \"not found\"}\n\n"
                    return
                payload = JobOut.model_validate(job).model_dump(mode="json")
                if payload != last:
                    yield f"data: {json.dumps(payload)}\n\n"
                    last = payload
                if job.status in ("completed", "failed", "cancelled"):
                    yield "event: end\ndata: {}\n\n"
                    return
            finally:
                db.close()
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
