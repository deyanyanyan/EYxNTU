"""Job lifecycle helpers shared by the API (enqueue/cancel/list) and the worker (claim/progress/finish)."""
from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.models.job import ACTIVE_STATUSES, FINISHED_STATUSES, Job, JobKind, JobStatus

WORKER_ID = f"{socket.gethostname()}"


def _now() -> datetime:
    return datetime.now(UTC)


# ---- API side ---------------------------------------------------------------
def enqueue(db: Session, kind: JobKind | str, payload: dict, *, project_id: str | None, started_by: str | None, supersede_key: str | None = None) -> Job:
    """Create a pending job. If `supersede_key` is given, any active job with the same
    kind and payload[supersede_key] is cancelled first (one ingest per source, etc.)."""
    kind_v = kind.value if isinstance(kind, JobKind) else kind
    if supersede_key and supersede_key in payload:
        for j in db.scalars(select(Job).where(Job.kind == kind_v, Job.status.in_(ACTIVE_STATUSES))):
            if j.payload.get(supersede_key) == payload[supersede_key]:
                j.status = JobStatus.CANCELLED.value
                j.error_type = "superseded"
                j.completed_at = _now()
    job = Job(kind=kind_v, payload=payload, project_id=project_id, started_by=started_by)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def request_cancel(db: Session, job_id: str) -> Job | None:
    job = db.get(Job, job_id)
    if not job:
        return None
    if job.status == JobStatus.PENDING.value:
        job.status = JobStatus.CANCELLED.value
        job.completed_at = _now()
    elif job.status == JobStatus.RUNNING.value:
        job.cancel_requested = True
    db.commit()
    return job


def list_jobs(db: Session, *, project_id: str | None = None, recent_minutes: int = 30, limit: int = 50) -> list[Job]:
    cutoff = _now() - timedelta(minutes=recent_minutes)
    stmt = select(Job).where((Job.status.in_(ACTIVE_STATUSES)) | (Job.completed_at >= cutoff))
    if project_id:
        stmt = stmt.where(Job.project_id == project_id)
    return list(db.scalars(stmt.order_by(Job.created_at.desc()).limit(limit)))


# ---- worker side ------------------------------------------------------------
def claim_next(db: Session, kinds: list[str] | None = None) -> Job | None:
    """Atomically claim one pending job using SKIP LOCKED so many workers can run."""
    kind_filter = "AND kind = ANY(:kinds)" if kinds else ""
    row = db.execute(
        text(
            f"""
            SELECT id FROM jobs
            WHERE status = 'pending' {kind_filter}
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"kinds": kinds} if kinds else {},
    ).first()
    if not row:
        db.rollback()
        return None
    db.execute(
        update(Job)
        .where(Job.id == row[0])
        .values(status=JobStatus.RUNNING.value, started_at=_now(), worker_id=WORKER_ID)
    )
    db.commit()
    return db.get(Job, row[0])


def progress(db: Session, job_id: str, *, current: int | None = None, total: int | None = None, message: str | None = None) -> None:
    values: dict = {}
    if current is not None:
        values["progress_current"] = current
    if total is not None:
        values["progress_total"] = total
    if message is not None:
        values["message"] = message
    if values:
        db.execute(update(Job).where(Job.id == job_id).values(**values))
        db.commit()


def is_cancelled(db: Session, job_id: str) -> bool:
    val = db.execute(select(Job.cancel_requested, Job.status).where(Job.id == job_id)).first()
    return bool(val and (val[0] or val[1] == JobStatus.CANCELLED.value))


def complete(db: Session, job_id: str, result: dict | None = None) -> None:
    db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status=JobStatus.COMPLETED.value, result=result, completed_at=_now(), message="done")
    )
    db.commit()


def fail(db: Session, job_id: str, error_type: str, error_message: str) -> None:
    db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status=JobStatus.FAILED.value, error_type=error_type, error_message=error_message[:4000], completed_at=_now())
    )
    db.commit()


def cancel_finalize(db: Session, job_id: str) -> None:
    db.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.CANCELLED.value, completed_at=_now()))
    db.commit()


def cleanup_stale(db: Session, max_age_minutes: int) -> int:
    cutoff = _now() - timedelta(minutes=max_age_minutes)
    res = db.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING.value, Job.started_at < cutoff)
        .values(status=JobStatus.FAILED.value, error_type="timeout", error_message=f"exceeded {max_age_minutes} minutes", completed_at=_now())
    )
    db.commit()
    return res.rowcount or 0


def delete_finished(db: Session) -> int:
    from sqlalchemy import delete

    res = db.execute(delete(Job).where(Job.status.in_(FINISHED_STATUSES)))
    db.commit()
    return res.rowcount or 0
