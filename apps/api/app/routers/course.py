"""Course authoring endpoints: plan, approve, generate lessons, export, download.

Every long-running step is a queued job; these endpoints only validate
preconditions, enqueue, and read back what the worker saved.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.deps import require_instructor
from app.core.auth.permissions import assert_project_access
from app.core.export.course import pick_asset
from app.core.export.service import latest_plan
from app.core.jobs import service as jobs
from app.db.session import get_db
from app.models.asset import Asset, AssetKind, Citation
from app.models.chunk import Chunk
from app.models.course import CoursePlan, Lesson, Module, PlanStatus
from app.models.job import ACTIVE_STATUSES, Job, JobKind
from app.models.project import Project
from app.models.review import Review
from app.models.source import Source, SourceStatus
from app.models.user import User
from app.schemas.course import AssetOut, CitationOut, ExportOut, LessonDetail, LessonSummary, ModuleOut, ObjectiveOut, PlanOut
from app.schemas.job import JobOut

router = APIRouter(prefix="/projects/{project_id}", tags=["course"])

_FILE_TYPES = {
    "scorm": ("application/zip", "course_scorm12.zip"),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "course.pptx"),
}


def _project(db: Session, actor: User, project_id: str, *, write: bool = False) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    assert_project_access(actor, p, write=write)
    return p


def _enqueue_once(db: Session, project_id: str, kind: JobKind, actor: User, what: str) -> Job:
    """One job of each kind per project at a time; a double click must not queue a second run."""
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == kind.value, Job.status.in_(ACTIVE_STATUSES)).limit(1))
    if running:
        raise HTTPException(status_code=409, detail=f"{what} is already running for this project.")
    return jobs.enqueue(db, kind, {"project_id": project_id}, project_id=project_id, started_by=actor.id)


def _lesson_summaries(db: Session, lessons: list[Lesson]) -> dict[str, LessonSummary]:
    ids = [lesson.id for lesson in lessons]
    assets = list(db.scalars(select(Asset).where(Asset.lesson_id.in_(ids)))) if ids else []
    out: dict[str, LessonSummary] = {}
    for lesson in lessons:
        mine = [a for a in assets if a.lesson_id == lesson.id]
        deck = pick_asset(mine, AssetKind.SLIDES.value)
        quiz = pick_asset(mine, AssetKind.QUIZ.value)
        stamps = [a.created_at for a in (deck, quiz) if a]
        out[lesson.id] = LessonSummary(
            id=lesson.id,
            position=lesson.position,
            title=lesson.title,
            estimated_minutes=lesson.estimated_minutes,
            objective_ids=list(lesson.objective_ids or []),
            source_chunk_count=len(lesson.source_chunk_ids or []),
            slides=len((deck.content or {}).get("slides", [])) if deck else 0,
            questions=len((quiz.content or {}).get("questions", [])) if quiz else 0,
            generated_at=max(stamps) if stamps else None,
        )
    return out


def _plan_out(db: Session, plan: CoursePlan) -> PlanOut:
    modules = list(db.scalars(select(Module).where(Module.plan_id == plan.id).order_by(Module.position)))
    lessons = [lesson for m in modules for lesson in m.lessons]
    summaries = _lesson_summaries(db, lessons)
    source_ids = list((plan.coverage or {}).keys())
    names = dict(db.execute(select(Source.id, Source.filename).where(Source.id.in_(source_ids))).all()) if source_ids else {}
    return PlanOut(
        id=plan.id,
        version=plan.version,
        title=plan.title,
        summary=plan.summary,
        status=plan.status,
        learning_objectives=[ObjectiveOut(**o) for o in plan.learning_objectives or []],
        coverage=plan.coverage,
        source_names=names,
        modules=[
            ModuleOut(id=m.id, position=m.position, title=m.title, description=m.description, lessons=[summaries[lesson.id] for lesson in m.lessons])
            for m in modules
        ],
        created_at=plan.created_at,
    )


# ---- plan -------------------------------------------------------------------
@router.post("/plan", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def request_plan(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id, write=True)
    ready = db.scalar(select(Source.id).where(Source.project_id == project_id, Source.status == SourceStatus.READY.value).limit(1))
    if not ready:
        raise HTTPException(status_code=409, detail="No sources are ready yet. Wait for ingestion to finish, then plan the course.")
    return _enqueue_once(db, project_id, JobKind.GENERATE_PLAN, actor, "Course planning")


@router.get("/plan", response_model=PlanOut)
def get_plan(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    plan = latest_plan(db, project_id)
    if not plan:
        raise HTTPException(status_code=404, detail="No course plan yet")
    return _plan_out(db, plan)


@router.post("/plan/{plan_id}/approve", response_model=PlanOut)
def approve_plan(project_id: str, plan_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id, write=True)
    plan = db.get(CoursePlan, plan_id)
    if not plan or plan.project_id != project_id:
        raise HTTPException(status_code=404, detail="Course plan not found")
    newest = latest_plan(db, project_id)
    if newest and newest.id != plan.id:
        raise HTTPException(status_code=409, detail=f"A newer plan (version {newest.version}) exists. Approve that one instead.")
    if plan.status != PlanStatus.APPROVED.value:
        plan.status = PlanStatus.APPROVED.value
        db.add(Review(reviewer_id=actor.id, target_type="plan", target_id=plan.id, decision="approve"))
        db.commit()
    return _plan_out(db, plan)


# ---- lessons ----------------------------------------------------------------
@router.post("/lessons/generate", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def request_lessons(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id, write=True)
    plan = latest_plan(db, project_id)
    if not plan or plan.status != PlanStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="Approve the latest course plan before generating lessons.")
    return _enqueue_once(db, project_id, JobKind.GENERATE_LESSON_ASSETS, actor, "Lesson generation")


@router.get("/lessons/{lesson_id}", response_model=LessonDetail)
def get_lesson(project_id: str, lesson_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    row = db.execute(
        select(Lesson, Module.title)
        .join(Module, Module.id == Lesson.module_id)
        .join(CoursePlan, CoursePlan.id == Module.plan_id)
        .where(Lesson.id == lesson_id, CoursePlan.project_id == project_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson, module_title = row
    assets = list(db.scalars(select(Asset).where(Asset.lesson_id == lesson.id)))
    deck = pick_asset(assets, AssetKind.SLIDES.value)
    quiz = pick_asset(assets, AssetKind.QUIZ.value)
    asset_ids = [a.id for a in (deck, quiz) if a]
    cites = db.execute(
        select(Citation, Chunk, Source.filename)
        .join(Chunk, Chunk.id == Citation.chunk_id)
        .join(Source, Source.id == Chunk.source_id)
        .where(Citation.asset_id.in_(asset_ids))
    ).all() if asset_ids else []
    return LessonDetail(
        lesson=_lesson_summaries(db, [lesson])[lesson.id],
        module_title=module_title,
        slides=AssetOut.model_validate(deck) if deck else None,
        quiz=AssetOut.model_validate(quiz) if quiz else None,
        citations=[
            CitationOut(
                block_id=c.block_id, chunk_id=c.chunk_id, quote=c.quote, source_name=filename,
                heading_path=chunk.heading_path, page_start=chunk.page_start, page_end=chunk.page_end, text=chunk.text,
            )
            for c, chunk, filename in cites
        ],
    )


# ---- export -----------------------------------------------------------------
@router.post("/export", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def request_export(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id, write=True)
    plan = latest_plan(db, project_id)
    has_content = plan and db.scalar(
        select(Asset.id).join(Lesson, Lesson.id == Asset.lesson_id).join(Module, Module.id == Lesson.module_id).where(Module.plan_id == plan.id).limit(1)
    )
    if not has_content:
        raise HTTPException(status_code=409, detail="Generate lessons for the latest plan before exporting.")
    return _enqueue_once(db, project_id, JobKind.PACKAGE_SCORM, actor, "Export")


@router.get("/exports", response_model=list[ExportOut])
def list_exports(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    return list(
        db.scalars(select(Asset).where(Asset.project_id == project_id, Asset.kind == AssetKind.SCORM.value).order_by(Asset.created_at.desc()).limit(20))
    )


@router.get("/exports/{asset_id}/files/{file_kind}")
def download_export(project_id: str, asset_id: str, file_kind: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    if file_kind not in _FILE_TYPES:
        raise HTTPException(status_code=404, detail="Unknown file type")
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id or asset.kind != AssetKind.SCORM.value:
        raise HTTPException(status_code=404, detail="Export not found")
    rel = ((asset.content or {}).get("files") or {}).get(file_kind)
    root = settings.data_dir.resolve()
    path = (root / rel).resolve() if rel else None
    if not path or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=410, detail="The export file is no longer on disk. Export again.")
    media_type, filename = _FILE_TYPES[file_kind]
    return FileResponse(Path(path), media_type=media_type, filename=filename)
