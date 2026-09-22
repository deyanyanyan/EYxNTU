"""Export job: latest plan's lessons -> editable PPTX + SCORM 1.2 package on disk.

Deterministic code only; no model calls. Files land under
DATA_DIR/artifacts/<project>/<timestamp>/ and are recorded as one project-level
SCORM asset whose content points at both files.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.export.course import course_from_db
from app.core.export.pptx_builder import build_pptx
from app.core.export.scorm_builder import build_scorm
from app.core.jobs import service as jobs
from app.models.asset import Asset, AssetKind
from app.models.course import CoursePlan

log = logging.getLogger(__name__)


def latest_plan(db: Session, project_id: str) -> CoursePlan | None:
    return db.scalar(select(CoursePlan).where(CoursePlan.project_id == project_id).order_by(CoursePlan.version.desc()).limit(1))


def export_course(db: Session, project_id: str, *, job_id: str | None = None) -> dict:
    started = time.perf_counter()
    plan = latest_plan(db, project_id)
    if not plan:
        raise ValueError("This project has no course plan to export.")
    course = course_from_db(db, plan)
    if not any(lesson.slides or lesson.questions for lesson in course.lessons):
        raise ValueError("No lesson has generated content yet. Generate lessons before exporting.")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    rel_dir = f"artifacts/{project_id}/{stamp}"
    out_dir = settings.data_dir / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if job_id:
        jobs.progress(db, job_id, current=0, total=2, message="Building PowerPoint")
    pptx_rel = f"{rel_dir}/course.pptx"
    (settings.data_dir / pptx_rel).write_bytes(build_pptx(course))

    if job_id:
        jobs.progress(db, job_id, current=1, total=2, message="Packaging SCORM 1.2")
    scorm_rel = f"{rel_dir}/course_scorm12.zip"
    (settings.data_dir / scorm_rel).write_bytes(build_scorm(course))

    lessons_with_content = sum(1 for lesson in course.lessons if lesson.slides or lesson.questions)
    asset = Asset(
        project_id=project_id,
        lesson_id=None,
        kind=AssetKind.SCORM.value,
        file_path=scorm_rel,
        content={
            "plan_id": plan.id,
            "plan_version": plan.version,
            "course_title": course.title,
            "files": {"scorm": scorm_rel, "pptx": pptx_rel},
            "lessons": lessons_with_content,
            "lessons_skipped_without_content": len(course.lessons) - lessons_with_content,
            "questions": course.question_count,
            "includes_unapproved": course.includes_unapproved,
        },
    )
    db.add(asset)
    db.commit()
    result = {"asset_id": asset.id, **asset.content, "seconds": round(time.perf_counter() - started, 1)}
    log.info("course exported: %s", result)
    return result
