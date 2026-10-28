"""Course authoring endpoints: outline, lessons, proposed changes, versions, export.

Every long-running step is a queued job; these endpoints only validate
preconditions, enqueue, and read back what the worker saved. Small changes that need
no model (outline edits, accepting a proposal, an author's own edit, approval,
restoring a version) happen here directly.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth.deps import require_instructor
from app.core.auth.permissions import assert_project_access
from app.core.export.course import pick_asset
from app.core.export.scorm_preview import open_session
from app.core.export.service import latest_plan
from app.core.generation import outline as outlines
from app.core.generation import revision
from app.core.generation.brief import question_findings
from app.core.jobs import service as jobs
from app.db.session import get_db
from app.models.asset import ApprovalState, Asset, AssetKind, Citation
from app.models.chunk import Chunk
from app.models.course import CoursePlan, Lesson, Module, PlanStatus
from app.models.job import ACTIVE_STATUSES, Job, JobKind
from app.models.project import Project
from app.models.review import Review
from app.models.source import Source, SourceStatus
from app.models.user import User
from app.schemas.course import (
    AssetOut,
    AssetVersionOut,
    BlockEdit,
    CitationOut,
    ExportOut,
    LessonDetail,
    LessonsRequest,
    LessonSummary,
    ModuleOut,
    NewSourceOut,
    ObjectiveOut,
    OutlineChangeOut,
    OutlineEdit,
    PlanOut,
    PlanVersionOut,
    PreviewOut,
    ProposalDecision,
    RestoreRequest,
    ReviseRequest,
    Steering,
)
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


# Runs that rewrite the same lessons must not overlap.
_EXCLUSIVE = {JobKind.GENERATE_LESSON_ASSETS.value: JobKind.REVISE_CONTENT.value, JobKind.REVISE_CONTENT.value: JobKind.GENERATE_LESSON_ASSETS.value}


def _enqueue_once(db: Session, project_id: str, kind: JobKind, actor: User, what: str, payload: dict | None = None) -> Job:
    """One job of each kind per project at a time; a double click must not queue a second run."""
    kinds = [kind.value, *([_EXCLUSIVE[kind.value]] if kind.value in _EXCLUSIVE else [])]
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind.in_(kinds), Job.status.in_(ACTIVE_STATUSES)).limit(1))
    if running:
        busy = what if running.kind == kind.value else "Another change to these lessons"
        raise HTTPException(status_code=409, detail=f"{busy} is already running for this project. Wait for it to finish.")
    return jobs.enqueue(db, kind, {"project_id": project_id, **(payload or {})}, project_id=project_id, started_by=actor.id)


def _lesson_summaries(db: Session, lessons: list[Lesson]) -> dict[str, LessonSummary]:
    ids = [lesson.id for lesson in lessons]
    assets = list(db.scalars(select(Asset).where(Asset.lesson_id.in_(ids)))) if ids else []
    out: dict[str, LessonSummary] = {}
    for lesson in lessons:
        mine = [a for a in assets if a.lesson_id == lesson.id]
        deck = pick_asset(mine, AssetKind.SLIDES.value)
        quiz = pick_asset(mine, AssetKind.QUIZ.value)
        stamps = [a.created_at for a in (deck, quiz) if a]
        review = (deck.critique or {}).get("reviewer") if deck else None
        quiz_review = (quiz.critique or {}).get("reviewer") if quiz else None
        current = [a for a in (deck, quiz) if a]
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
            reviewer_flags=sum(len(s.get("issues") or []) for s in review.get("slides", {}).values()) if review else None,
            weak_questions=sum(1 for b in (quiz_review or {}).get("questions", {}) if question_findings(quiz.critique, b)) if quiz_review else 0,
            approved=bool(current) and all(a.approval == ApprovalState.APPROVED.value for a in current),
            proposals=sum(len((a.content or {}).get(revision.PROPOSALS, [])) for a in current),
        )
    return out


def _sources_as_of(plan: CoursePlan) -> datetime:
    """When the outline last took in the sources; an edited copy inherits its original's."""
    inherited = (plan.meta or {}).get("sources_as_of")
    return datetime.fromisoformat(inherited) if inherited else plan.created_at


def _plan_out(db: Session, plan: CoursePlan, *, latest: bool = True) -> PlanOut:
    modules = list(db.scalars(select(Module).where(Module.plan_id == plan.id).order_by(Module.position)))
    lessons = [lesson for m in modules for lesson in m.lessons]
    summaries = _lesson_summaries(db, lessons)
    source_ids = list((plan.coverage or {}).keys())
    names = dict(db.execute(select(Source.id, Source.filename).where(Source.id.in_(source_ids))).all()) if source_ids else {}
    # The course last absorbed sources when the plan was made or, later, when lessons were
    # generated from it (lessons retrieve from every source). Sources ready after that are new.
    built = db.scalar(
        select(func.max(Asset.created_at)).join(Lesson, Lesson.id == Asset.lesson_id).join(Module, Module.id == Lesson.module_id).where(Module.plan_id == plan.id)
    )
    since = max(_sources_as_of(plan), built) if built else _sources_as_of(plan)
    newer = db.scalars(
        select(Source).where(Source.project_id == plan.project_id, Source.status == SourceStatus.READY.value, Source.updated_at > since).order_by(Source.updated_at)
    )
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
        new_sources=[NewSourceOut(id=s.id, filename=s.filename, ready_at=s.updated_at) for s in newer] if latest else [],
        meta=plan.meta,
        latest=latest,
    )


def _plan_version(db: Session, project_id: str, version: int | None) -> CoursePlan:
    plan = latest_plan(db, project_id) if version is None else db.scalar(
        select(CoursePlan).where(CoursePlan.project_id == project_id, CoursePlan.version == version)
    )
    if not plan:
        raise HTTPException(status_code=404, detail="No course outline yet" if version is None else f"No outline version {version}")
    return plan


def _latest_editable(db: Session, project_id: str, plan_id: str) -> CoursePlan:
    plan = db.get(CoursePlan, plan_id)
    if not plan or plan.project_id != project_id:
        raise HTTPException(status_code=404, detail="Course outline not found")
    newest = latest_plan(db, project_id)
    if newest and newest.id != plan.id:
        raise HTTPException(status_code=409, detail=f"Outline version {newest.version} is newer. Edit that one.")
    return plan


# ---- plan -------------------------------------------------------------------
@router.post("/plan", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def request_plan(project_id: str, body: Steering | None = Body(default=None), actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Generate the outline, or rebuild it as a new version, optionally with instructions."""
    _project(db, actor, project_id, write=True)
    ready = db.scalar(select(Source.id).where(Source.project_id == project_id, Source.status == SourceStatus.READY.value).limit(1))
    if not ready:
        raise HTTPException(status_code=409, detail="No sources are ready yet. Wait for ingestion to finish, then plan the course.")
    steering = body or Steering()
    return _enqueue_once(db, project_id, JobKind.GENERATE_PLAN, actor, "Course planning", {"instructions": steering.instructions, "intents": steering.intents})


@router.get("/plan", response_model=PlanOut)
def get_plan(project_id: str, version: int | None = None, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """The latest outline, or an earlier ``version`` (read-only)."""
    _project(db, actor, project_id)
    plan = _plan_version(db, project_id, version)
    newest = latest_plan(db, project_id)
    return _plan_out(db, plan, latest=newest is not None and newest.id == plan.id)


@router.get("/plan/versions", response_model=list[PlanVersionOut])
def plan_versions(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    plans = list(db.scalars(select(CoursePlan).where(CoursePlan.project_id == project_id).order_by(CoursePlan.version.desc())))
    return [
        PlanVersionOut(id=p.id, version=p.version, status=p.status, title=p.title, created_at=p.created_at, meta=p.meta,
                       lessons=sum(len(m.lessons) for m in p.modules))
        for p in plans
    ]


@router.get("/plan/{plan_id}/changes", response_model=list[OutlineChangeOut])
def plan_changes(project_id: str, plan_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """What changed from the previous outline version to this one."""
    _project(db, actor, project_id)
    plan = db.get(CoursePlan, plan_id)
    if not plan or plan.project_id != project_id:
        raise HTTPException(status_code=404, detail="Course outline not found")
    previous = db.scalar(select(CoursePlan).where(CoursePlan.project_id == project_id, CoursePlan.version < plan.version).order_by(CoursePlan.version.desc()).limit(1))
    return [OutlineChangeOut(**c) for c in outlines.compare(previous, plan)] if previous else []


@router.patch("/plan/{plan_id}/outline", response_model=PlanOut)
def edit_outline(project_id: str, plan_id: str, edit: OutlineEdit, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """One direct edit. A draft changes in place; an approved outline becomes a new draft version."""
    _project(db, actor, project_id, write=True)
    plan = _latest_editable(db, project_id, plan_id)
    try:
        edited = outlines.apply_edit(db, plan, edit.model_dump())
    except outlines.OutlineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _plan_out(db, edited)


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
def request_lessons(project_id: str, body: LessonsRequest | None = Body(default=None), actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Generate or regenerate lessons: all of them, or the chosen ones, with optional instructions.
    The new content applies at once; the version it replaces stays restorable."""
    _project(db, actor, project_id, write=True)
    plan = latest_plan(db, project_id)
    if not plan or plan.status != PlanStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="Approve the latest course outline before generating lessons.")
    request = body or LessonsRequest()
    if request.lesson_ids:
        known = {lesson.id for m in plan.modules for lesson in m.lessons}
        if not set(request.lesson_ids) <= known:
            raise HTTPException(status_code=422, detail="Some of those lessons are not in the current outline. Reload the course.")
    return _enqueue_once(db, project_id, JobKind.GENERATE_LESSON_ASSETS, actor, "Lesson generation", request.model_dump())


@router.post("/lessons/revise", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def request_revision(project_id: str, body: ReviseRequest, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Proposed changes for chosen slides and questions, or fixes for everything flagged in chosen lessons."""
    _project(db, actor, project_id, write=True)
    if not body.targets and not (body.fix and body.lesson_ids):
        raise HTTPException(status_code=422, detail="Choose the slides or questions to change, or lessons to fix.")
    return _enqueue_once(db, project_id, JobKind.REVISE_CONTENT, actor, "Preparing changes", body.model_dump())


def _lesson_in_project(db: Session, project_id: str, lesson_id: str) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    plan = db.get(CoursePlan, db.get(Module, lesson.module_id).plan_id) if lesson else None
    if not lesson or plan.project_id != project_id:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson


def _current(db: Session, lesson_id: str, kind: str) -> Asset:
    asset = revision.current(db, lesson_id, AssetKind.SLIDES.value if kind in ("slide", "slides") else AssetKind.QUIZ.value)
    if not asset:
        raise HTTPException(status_code=404, detail="This lesson has no generated content yet")
    return asset


def _revised(db: Session, project_id: str, lesson_id: str, actor: User, change) -> LessonDetail:
    """Run a revision step, turning its refusals into 409s, then return the lesson as it now is."""
    try:
        change()
    except revision.RevisionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return get_lesson(project_id, lesson_id, actor=actor, db=db)


@router.post("/lessons/{lesson_id}/approve", response_model=LessonDetail)
def approve_lesson(project_id: str, lesson_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id, write=True)
    _lesson_in_project(db, project_id, lesson_id)
    return _revised(db, project_id, lesson_id, actor, lambda: revision.set_approval(db, lesson_id, True, actor.id))


@router.post("/lessons/{lesson_id}/reopen", response_model=LessonDetail)
def reopen_lesson(project_id: str, lesson_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id, write=True)
    _lesson_in_project(db, project_id, lesson_id)
    return _revised(db, project_id, lesson_id, actor, lambda: revision.set_approval(db, lesson_id, False, actor.id))


@router.get("/lessons/{lesson_id}/versions", response_model=list[AssetVersionOut])
def lesson_versions(project_id: str, lesson_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    _lesson_in_project(db, project_id, lesson_id)
    current = {a.id for a in (revision.current(db, lesson_id, k) for k in (AssetKind.SLIDES.value, AssetKind.QUIZ.value)) if a}
    return [
        AssetVersionOut(
            asset_id=a.id, kind=a.kind, version=a.version, created_at=a.created_at, current=a.id in current, approval=a.approval,
            note=((a.content or {}).get("revision") or {}).get("note") or "Generated lesson",
            instructions=((a.content or {}).get("revision") or {}).get("instructions"),
        )
        for a in revision.history(db, lesson_id)
    ]


@router.post("/lessons/{lesson_id}/restore", response_model=LessonDetail)
def restore_version(project_id: str, lesson_id: str, body: RestoreRequest, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id, write=True)
    _lesson_in_project(db, project_id, lesson_id)
    return _revised(db, project_id, lesson_id, actor, lambda: revision.restore(db, lesson_id, body.asset_id))


@router.post("/lessons/{lesson_id}/proposals/{decision}", response_model=LessonDetail)
def decide_proposals(project_id: str, lesson_id: str, decision: str, body: ProposalDecision | None = Body(default=None),
                     actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Accept or discard waiting proposals (``ids``, or all of them) on the lesson's slides and quiz."""
    if decision not in ("accept", "discard"):
        raise HTTPException(status_code=404, detail="Unknown decision")
    _project(db, actor, project_id, write=True)
    _lesson_in_project(db, project_id, lesson_id)
    ids = (body or ProposalDecision()).ids

    def change() -> None:
        touched = 0
        for kind in (AssetKind.SLIDES.value, AssetKind.QUIZ.value):
            asset = revision.current(db, lesson_id, kind)
            waiting = [p for p in (asset.content or {}).get(revision.PROPOSALS, []) if ids is None or p["id"] in ids] if asset else []
            if not waiting:
                continue
            touched += len(waiting)
            if decision == "accept":
                revision.accept_proposals(db, asset, [p["id"] for p in waiting])
            else:
                revision.discard_proposals(asset, [p["id"] for p in waiting])
        if not touched:
            raise revision.RevisionError("Those proposed changes are no longer waiting")

    return _revised(db, project_id, lesson_id, actor, change)


@router.patch("/lessons/{lesson_id}/blocks", response_model=LessonDetail)
def edit_lesson_block(project_id: str, lesson_id: str, edit: BlockEdit, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """The author's own edit to one slide or question, saved as a new version."""
    _project(db, actor, project_id, write=True)
    _lesson_in_project(db, project_id, lesson_id)
    asset = _current(db, lesson_id, edit.kind)
    return _revised(db, project_id, lesson_id, actor, lambda: revision.edit_block(db, asset, edit.block, edit.value))


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


def _export_file(db: Session, project_id: str, asset_id: str, file_kind: str) -> tuple[Asset, str, Path]:
    """An export asset of this project, and one of its files' DATA_DIR-relative and absolute paths."""
    asset = db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id or asset.kind != AssetKind.SCORM.value:
        raise HTTPException(status_code=404, detail="Export not found")
    rel = ((asset.content or {}).get("files") or {}).get(file_kind)
    root = settings.data_dir.resolve()
    path = (root / rel).resolve() if rel else None
    if not path or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=410, detail="The export file is no longer on disk. Export again.")
    return asset, rel, path


@router.get("/exports/{asset_id}/files/{file_kind}")
def download_export(project_id: str, asset_id: str, file_kind: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    _project(db, actor, project_id)
    if file_kind not in _FILE_TYPES:
        raise HTTPException(status_code=404, detail="Unknown file type")
    _, _, path = _export_file(db, project_id, asset_id, file_kind)
    media_type, filename = _FILE_TYPES[file_kind]
    return FileResponse(path, media_type=media_type, filename=filename)


@router.post("/exports/{asset_id}/preview", response_model=PreviewOut)
def preview_export(project_id: str, asset_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """Start an in-app preview of the export's SCORM package (app/core/export/scorm_preview.py)."""
    _project(db, actor, project_id)
    asset, rel, _ = _export_file(db, project_id, asset_id, "scorm")
    try:
        session = open_session(rel, user_id=actor.id, asset_id=asset.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreviewOut(**session, export=ExportOut.model_validate(asset))
