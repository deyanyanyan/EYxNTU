"""Direct edits to a course outline, and comparing outline versions.

A draft outline is edited in place. Editing an approved outline first copies it to a
new draft version, so the approved version keeps its meaning until the new one is
approved. The copy carries every lesson's current slides and quiz across, so renaming
or reordering lessons never means regenerating them. Each copied lesson remembers the
lesson it came from (``origin_id``), which is how versions are compared lesson by lesson.
"""
from __future__ import annotations

import copy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.export.course import pick_asset
from app.models.asset import Asset, AssetKind, Citation
from app.models.course import CoursePlan, Lesson, Module, PlanStatus

OPS = ("rename_course", "rename_module", "rename_lesson", "move_lesson", "add_lesson", "remove_lesson")
MAX_TITLE = 512


class OutlineError(ValueError):
    pass


def lineage(lesson: Lesson) -> str:
    """The same lesson across outline versions shares this id."""
    return lesson.origin_id or lesson.id


def ordered(plan: CoursePlan) -> list[tuple[Module, Lesson]]:
    return [(m, lesson) for m in sorted(plan.modules, key=lambda m: m.position) for lesson in sorted(m.lessons, key=lambda le: le.position)]


def copy_plan(db: Session, plan: CoursePlan, change: str) -> tuple[CoursePlan, dict[str, str], dict[str, str]]:
    """A new draft version of ``plan`` with every lesson's current content; returns it and the old->new id maps."""
    version = (db.scalar(select(func.max(CoursePlan.version)).where(CoursePlan.project_id == plan.project_id)) or 0) + 1
    new = CoursePlan(
        project_id=plan.project_id, version=version, title=plan.title, summary=plan.summary,
        learning_objectives=copy.deepcopy(plan.learning_objectives or []), status=PlanStatus.DRAFT.value,
        coverage=copy.deepcopy(plan.coverage),
        meta={"note": "Edited outline", "edited_from": plan.version, "changes": [change],
              # the copy has taken in no sources that its original had not
              "sources_as_of": (plan.meta or {}).get("sources_as_of") or plan.created_at.isoformat()},
    )
    modules: dict[str, str] = {}
    lessons: dict[str, Lesson] = {}
    for m in sorted(plan.modules, key=lambda m: m.position):
        nm = Module(position=m.position, title=m.title, description=m.description)
        for lesson in sorted(m.lessons, key=lambda le: le.position):
            nl = Lesson(position=lesson.position, title=lesson.title, objective_ids=list(lesson.objective_ids or []),
                        estimated_minutes=lesson.estimated_minutes, source_chunk_ids=list(lesson.source_chunk_ids or []), origin_id=lineage(lesson))
            nm.lessons.append(nl)
            lessons[lesson.id] = nl
        new.modules.append(nm)
        modules[m.id] = nm
    db.add(new)
    db.flush()

    old_assets = list(db.scalars(select(Asset).where(Asset.lesson_id.in_(list(lessons))))) if lessons else []
    for old_id, nl in lessons.items():
        mine = [a for a in old_assets if a.lesson_id == old_id]
        for kind in (AssetKind.SLIDES.value, AssetKind.QUIZ.value):
            a = pick_asset(mine, kind)
            if not a:
                continue
            clone = Asset(project_id=a.project_id, lesson_id=nl.id, kind=a.kind, version=a.version, content=copy.deepcopy(a.content),
                          approval=a.approval, critique=copy.deepcopy(a.critique), generated_with_model=a.generated_with_model,
                          prompt_version_id=a.prompt_version_id, created_at=a.created_at)
            clone.citations = [Citation(block_id=c.block_id, chunk_id=c.chunk_id, similarity=c.similarity, quote=c.quote) for c in a.citations]
            db.add(clone)
    db.flush()
    return new, {k: v.id for k, v in modules.items()}, {k: v.id for k, v in lessons.items()}


def _title(value: object) -> str:
    title = str(value or "").strip()
    if not title:
        raise OutlineError("A title cannot be empty")
    return title[:MAX_TITLE]


def _find(plan: CoursePlan, lesson_id: str | None = None, module_id: str | None = None):
    for m in plan.modules:
        if module_id and m.id == module_id:
            return m
        for lesson in m.lessons:
            if lesson_id and lesson.id == lesson_id:
                return lesson
    raise OutlineError("That part of the outline no longer exists. Reload the outline.")


def describe(plan: CoursePlan, op: dict) -> str:
    kind = op.get("op")
    if kind == "rename_course":
        return f"Renamed the course to “{op.get('title', '').strip()}”"
    if kind == "rename_module":
        return f"Renamed module “{_find(plan, module_id=op.get('module_id')).title}”"
    if kind == "add_lesson":
        return f"Added lesson “{op.get('title', '').strip()}”"
    lesson = _find(plan, lesson_id=op.get("lesson_id"))
    return {"rename_lesson": f"Renamed lesson “{lesson.title}”", "move_lesson": f"Moved lesson “{lesson.title}”",
            "remove_lesson": f"Removed lesson “{lesson.title}”"}.get(kind, kind)


def apply_edit(db: Session, plan: CoursePlan, op: dict) -> CoursePlan:
    """Apply one edit; returns the outline that holds it (a new draft when ``plan`` was approved)."""
    kind = op.get("op")
    if kind not in OPS:
        raise OutlineError(f"Unknown outline edit {kind!r}")
    change = describe(plan, op)
    if plan.status == PlanStatus.APPROVED.value:
        plan, module_map, lesson_map = copy_plan(db, plan, change)
        op = {**op, "module_id": module_map.get(op.get("module_id"), op.get("module_id")), "lesson_id": lesson_map.get(op.get("lesson_id"), op.get("lesson_id"))}
        db.refresh(plan)
    else:
        meta = dict(plan.meta or {})
        meta["changes"] = [*meta.get("changes", []), change]
        plan.meta = meta

    if kind == "rename_course":
        plan.title = _title(op.get("title"))
    elif kind == "rename_module":
        _find(plan, module_id=op.get("module_id")).title = _title(op.get("title"))
    elif kind == "rename_lesson":
        _find(plan, lesson_id=op.get("lesson_id")).title = _title(op.get("title"))
    elif kind == "add_lesson":
        module = _find(plan, module_id=op.get("module_id"))
        module.lessons.append(Lesson(position=max((le.position for le in module.lessons), default=0) + 1, title=_title(op.get("title")),
                                     estimated_minutes=10, objective_ids=[], source_chunk_ids=[]))
    elif kind == "move_lesson":
        lesson = _find(plan, lesson_id=op.get("lesson_id"))
        siblings = sorted(next(m for m in plan.modules if m.id == lesson.module_id).lessons, key=lambda le: le.position)
        at = siblings.index(lesson)
        to = at + (1 if int(op.get("delta", 1)) > 0 else -1)
        if 0 <= to < len(siblings):
            siblings[at].position, siblings[to].position = siblings[to].position, siblings[at].position
    elif kind == "remove_lesson":
        lesson = _find(plan, lesson_id=op.get("lesson_id"))
        module = next(m for m in plan.modules if m.id == lesson.module_id)
        module.lessons.remove(lesson)
        db.delete(lesson)
        for i, le in enumerate(sorted(module.lessons, key=lambda le: le.position), 1):
            le.position = i
    db.flush()
    return plan


def compare(older: CoursePlan, newer: CoursePlan) -> list[dict]:
    """What changed from ``older`` to ``newer``, lesson by lesson, in the newer outline's order."""
    def index(plan: CoursePlan) -> dict[str, tuple[str, int, int, str]]:
        out = {}
        for m, lesson in ordered(plan):
            out[lineage(lesson)] = (m.title, m.position, lesson.position, lesson.title)
        return out

    old, new = index(older), index(newer)
    changes: list[dict] = []
    if older.title != newer.title:
        changes.append({"kind": "renamed", "what": "course", "detail": f"“{older.title}” → “{newer.title}”"})
    for key, (module, mpos, lpos, title) in new.items():
        if key not in old:
            changes.append({"kind": "added", "what": "lesson", "detail": f"“{title}” in {module}"})
            continue
        o_module, o_mpos, o_lpos, o_title = old[key]
        if o_title != title:
            changes.append({"kind": "renamed", "what": "lesson", "detail": f"“{o_title}” → “{title}”"})
        if (o_mpos, o_lpos) != (mpos, lpos):
            changes.append({"kind": "moved", "what": "lesson", "detail": f"“{title}” from {o_mpos}.{o_lpos} to {mpos}.{lpos}"})
    for key, (module, _, _, title) in old.items():
        if key not in new:
            changes.append({"kind": "removed", "what": "lesson", "detail": f"“{title}” from {module}"})
    return changes
