"""A database-free snapshot of a course for the exporters.

The PPTX and SCORM builders take an ExportCourse rather than ORM objects, so
they are deterministic, testable without PostgreSQL, and cannot accidentally
trigger lazy loads or writes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import ApprovalState, Asset, AssetKind
from app.models.course import CoursePlan, Lesson, Module

_MARKER = re.compile(r"\[(\d{1,3})\]")


@dataclass
class ExportLesson:
    module_title: str
    title: str
    estimated_minutes: int | None
    slides: list[dict] = field(default_factory=list)
    references: dict[str, dict] = field(default_factory=dict)
    questions: list[dict] = field(default_factory=list)
    quiz_references: dict[str, dict] = field(default_factory=dict)


@dataclass
class ExportCourse:
    id: str
    title: str
    summary: str
    objectives: list[dict]
    lessons: list[ExportLesson]
    includes_unapproved: bool = False

    @property
    def question_count(self) -> int:
        return sum(len(lesson.questions) for lesson in self.lessons)


def source_label(ref: dict) -> str:
    label = ref.get("source_name") or "Source"
    if ref.get("heading_path"):
        label += f" › {ref['heading_path']}"
    start, end = ref.get("page_start"), ref.get("page_end")
    if start:
        label += f" (p.{start}{f'–{end}' if end and end != start else ''})"
    return label


def used_reference_numbers(slides: list[dict]) -> list[str]:
    """Reference numbers actually cited in a deck, in first-use order."""
    found: list[str] = []
    for s in slides:
        cells = [c for row in (s.get("table") or []) for c in row]
        for text in [s.get("title", ""), *s.get("bullets", []), *cells, s.get("notes", "")]:
            for n in _MARKER.findall(text or ""):
                if n not in found:
                    found.append(n)
    return found


def strip_markers(text: str) -> str:
    return re.sub(r"\s*\[\d{1,3}\]", "", text or "").strip()


def reference_for_chunk(references: dict[str, dict], chunk_id: str | None) -> dict | None:
    return next((r for r in references.values() if r.get("chunk_id") == chunk_id), None) if chunk_id else None


def pick_asset(assets: list[Asset], kind: str) -> Asset | None:
    """The current asset of a kind: an approved one if any, else the newest. Superseded
    versions (kept for restore) never count."""
    of_kind = [a for a in assets if a.kind == kind and a.superseded_at is None]
    approved = [a for a in of_kind if a.approval == ApprovalState.APPROVED.value]
    pool = approved or of_kind
    return max(pool, key=lambda a: (a.version, a.created_at)) if pool else None


def course_from_db(db: Session, plan: CoursePlan) -> ExportCourse:
    rows = db.execute(
        select(Lesson, Module.title).join(Module, Module.id == Lesson.module_id).where(Module.plan_id == plan.id).order_by(Module.position, Lesson.position)
    ).all()
    lesson_ids = [lesson.id for lesson, _ in rows]
    assets = list(db.scalars(select(Asset).where(Asset.lesson_id.in_(lesson_ids)))) if lesson_ids else []

    out: list[ExportLesson] = []
    unapproved = False
    for lesson, module_title in rows:
        mine = [a for a in assets if a.lesson_id == lesson.id]
        deck = pick_asset(mine, AssetKind.SLIDES.value)
        quiz = pick_asset(mine, AssetKind.QUIZ.value)
        unapproved |= any(a and a.approval != ApprovalState.APPROVED.value for a in (deck, quiz))
        out.append(
            ExportLesson(
                module_title=module_title,
                title=lesson.title,
                estimated_minutes=lesson.estimated_minutes,
                slides=list((deck.content or {}).get("slides", [])) if deck else [],
                references=dict((deck.content or {}).get("references", {})) if deck else {},
                questions=list((quiz.content or {}).get("questions", [])) if quiz else [],
                quiz_references=dict((quiz.content or {}).get("references", {})) if quiz else {},
            )
        )
    return ExportCourse(
        id=plan.id,
        title=plan.title,
        summary=plan.summary or "",
        objectives=list(plan.learning_objectives or []),
        lessons=out,
        includes_unapproved=unapproved,
    )
