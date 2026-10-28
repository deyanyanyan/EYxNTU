"""Job handlers keyed by JobKind value.

Each handler: (db, job_id, payload) -> result dict. It should call
`jobs.progress(...)` as it goes and check `jobs.is_cancelled(...)` inside loops.
Handlers for later milestones are registered as stubs so the job centre
already knows their names; replace the body when the milestone lands.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from app.core.export.service import export_course
from app.core.generation.lesson.service import generate_lessons
from app.core.generation.plan.service import generate_plan
from app.core.generation.revise import propose
from app.core.jobs import service as jobs
from app.core.llm.client import run_blocking
from app.core.rag.ingest import ingest_source
from app.models.job import JobKind

Handler = Callable[[Session, str, dict], dict]


def handle_ingest_source(db: Session, job_id: str, payload: dict) -> dict:
    return ingest_source(db, payload["source_id"], job_id=job_id)


def handle_generate_plan(db: Session, job_id: str, payload: dict) -> dict:
    return run_blocking(generate_plan(db, payload["project_id"], job_id=job_id, instructions=payload.get("instructions"), intents=payload.get("intents")))


def handle_generate_lessons(db: Session, job_id: str, payload: dict) -> dict:
    return run_blocking(generate_lessons(
        db, payload["project_id"], job_id=job_id, lesson_ids=payload.get("lesson_ids") or None,
        instructions=payload.get("instructions"), intents=payload.get("intents"),
    ))


def handle_revise_content(db: Session, job_id: str, payload: dict) -> dict:
    return run_blocking(propose(
        db, payload["project_id"], targets=payload.get("targets") or [], lesson_ids=payload.get("lesson_ids") or [], fix=bool(payload.get("fix")),
        instructions=payload.get("instructions"), intents=payload.get("intents") or [], job_id=job_id,
    ))


def handle_export_course(db: Session, job_id: str, payload: dict) -> dict:
    return export_course(db, payload["project_id"], job_id=job_id)


def _not_implemented(kind: str) -> Handler:
    def _h(db: Session, job_id: str, payload: dict) -> dict:
        jobs.progress(db, job_id, message=f"{kind} is scheduled for a later milestone; see docs/ROADMAP.md")
        raise NotImplementedError(kind)

    return _h


HANDLERS: dict[str, Handler] = {
    JobKind.INGEST_SOURCE.value: handle_ingest_source,
    # Single-pass baseline: no critique, no gates. See docs/HANDOFF.md.
    JobKind.GENERATE_PLAN.value: handle_generate_plan,
    JobKind.GENERATE_LESSON_ASSETS.value: handle_generate_lessons,
    JobKind.CRITIQUE_ASSET.value: _not_implemented("critique_asset"),          # M3
    JobKind.RENDER_SLIDES.value: _not_implemented("render_slides"),            # M3
    JobKind.RENDER_VIDEO.value: _not_implemented("render_video"),              # M4
    JobKind.PACKAGE_SCORM.value: handle_export_course,                         # PPTX + SCORM 1.2
    JobKind.EVAL_RUN.value: _not_implemented("eval_run"),                      # M5
    JobKind.REVISE_CONTENT.value: handle_revise_content,                       # proposed changes and fixes
}
