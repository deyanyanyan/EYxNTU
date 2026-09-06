"""Job handlers keyed by JobKind value.

Each handler: (db, job_id, payload) -> result dict. It should call
`jobs.progress(...)` as it goes and check `jobs.is_cancelled(...)` inside loops.
Handlers for later milestones are registered as stubs so the job centre
already knows their names; replace the body when the milestone lands.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from app.core.jobs import service as jobs
from app.core.rag.ingest import ingest_source
from app.models.job import JobKind

Handler = Callable[[Session, str, dict], dict]


def handle_ingest_source(db: Session, job_id: str, payload: dict) -> dict:
    return ingest_source(db, payload["source_id"], job_id=job_id)


def _not_implemented(kind: str) -> Handler:
    def _h(db: Session, job_id: str, payload: dict) -> dict:
        jobs.progress(db, job_id, message=f"{kind} is scheduled for a later milestone; see docs/ROADMAP.md")
        raise NotImplementedError(kind)

    return _h


HANDLERS: dict[str, Handler] = {
    JobKind.INGEST_SOURCE.value: handle_ingest_source,
    JobKind.GENERATE_PLAN.value: _not_implemented("generate_plan"),            # M2
    JobKind.GENERATE_LESSON_ASSETS.value: _not_implemented("generate_lesson_assets"),  # M3
    JobKind.CRITIQUE_ASSET.value: _not_implemented("critique_asset"),          # M3
    JobKind.RENDER_SLIDES.value: _not_implemented("render_slides"),            # M3
    JobKind.RENDER_VIDEO.value: _not_implemented("render_video"),              # M4
    JobKind.PACKAGE_SCORM.value: _not_implemented("package_scorm"),            # M4
    JobKind.EVAL_RUN.value: _not_implemented("eval_run"),                      # M5
}
