"""Keep a course's citations working when one of its sources is re-ingested.

Re-ingesting a source replaces its chunks with new rows. Course content points at chunk
ids in several places: citation rows, each asset's reference table and quiz questions,
each lesson's planned chunks, and the plan's objectives. Deleting the old chunks used to
cascade-delete the citations and leave the other ids pointing at nothing.

Instead, ingestion retires the old chunks (``Chunk.retired_at``) before writing new ones,
then calls :func:`carry_over`:

1. Every retired chunk whose text is unchanged is matched to its new chunk, and every
   reference to it is moved to the new id. A re-upload of the same document therefore
   changes nothing for the course.
2. Retired chunks the course still refers to but whose text changed are kept, so their
   citations still show the passage the content was written from. Retrieval and planning
   ignore them; ``Citation.chunk.retired_at`` tells the UI the source has since changed.
3. Retired chunks nothing refers to are deleted.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Citation
from app.models.chunk import Chunk
from app.models.course import CoursePlan, Lesson, Module


def normalise(text: str) -> str:
    """Whitespace-insensitive key, so a re-parse that only reflows lines still matches."""
    return " ".join(text.split())


def match_chunks(retired: list[tuple[str, int, str]], live: list[tuple[str, int, str]]) -> dict[str, str]:
    """Map retired chunk ids to live ones with the same text: ``(id, chunk_index, text)`` each.

    When the same text appears more than once (repeated boilerplate), the live chunk
    nearest in document position wins.
    """
    by_text: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for cid, index, text in live:
        by_text[normalise(text)].append((index, cid))
    mapping: dict[str, str] = {}
    for cid, index, text in retired:
        candidates = by_text.get(normalise(text))
        if candidates:
            mapping[cid] = min(candidates, key=lambda c: abs(c[0] - index))[1]
    return mapping


def swap_ids(value: Any, mapping: dict[str, str]) -> tuple[Any, bool]:
    """Copy of a JSON value with every string equal to a mapped id replaced. Ids are UUIDs,
    so an exact string match cannot hit ordinary text."""
    if isinstance(value, str):
        new = mapping.get(value)
        return (new, True) if new else (value, False)
    if isinstance(value, list):
        changed = False
        out = []
        for item in value:
            item, c = swap_ids(item, mapping)
            out.append(item)
            changed |= c
        return out, changed
    if isinstance(value, dict):
        changed = False
        out_d = {}
        for k, item in value.items():
            item, c = swap_ids(item, mapping)
            out_d[k] = item
            changed |= c
        return out_d, changed
    return value, False


def ids_in(value: Any, wanted: set[str]) -> set[str]:
    """Which of ``wanted`` occur as strings anywhere in a JSON value."""
    if isinstance(value, str):
        return {value} if value in wanted else set()
    if isinstance(value, list):
        return set().union(*(ids_in(v, wanted) for v in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(ids_in(v, wanted) for v in value.values())) if value else set()
    return set()


def _json_holders(db: Session, project_id: str) -> list[tuple[object, str]]:
    """Every (row, attribute) in the project that can hold chunk ids inside JSON."""
    holders: list[tuple[object, str]] = []
    holders += [(a, "content") for a in db.scalars(select(Asset).where(Asset.project_id == project_id, Asset.content.is_not(None)))]
    plans = list(db.scalars(select(CoursePlan).where(CoursePlan.project_id == project_id)))
    holders += [(p, "learning_objectives") for p in plans]
    if plans:
        lessons = db.scalars(select(Lesson).join(Module, Module.id == Lesson.module_id).where(Module.plan_id.in_([p.id for p in plans])))
        holders += [(lesson, "source_chunk_ids") for lesson in lessons]
    return holders


def carry_over(db: Session, source_id: str, project_id: str) -> dict:
    """Move course references from the source's retired chunks to its live ones; see module doc."""
    retired = db.execute(
        select(Chunk.id, Chunk.chunk_index, Chunk.text).where(Chunk.source_id == source_id, Chunk.retired_at.is_not(None))
    ).all()
    if not retired:
        return {"carried": 0, "kept": 0, "removed": 0}
    live = db.execute(
        select(Chunk.id, Chunk.chunk_index, Chunk.text).where(Chunk.source_id == source_id, Chunk.retired_at.is_(None))
    ).all()
    mapping = match_chunks([tuple(r) for r in retired], [tuple(r) for r in live])
    holders = _json_holders(db, project_id)

    if mapping:
        for citation in db.scalars(select(Citation).where(Citation.chunk_id.in_(list(mapping)))):
            citation.chunk_id = mapping[citation.chunk_id]
        for row, attr in holders:
            new, changed = swap_ids(getattr(row, attr), mapping)
            if changed:
                setattr(row, attr, new)  # a new object, so SQLAlchemy sees the JSONB change
        db.flush()

    retired_ids = {r.id for r in retired}
    still_used = set(db.scalars(select(Citation.chunk_id).where(Citation.chunk_id.in_(list(retired_ids)))))
    for row, attr in holders:
        still_used |= ids_in(getattr(row, attr), retired_ids)
    unused = retired_ids - still_used
    if unused:
        db.execute(delete(Chunk).where(Chunk.id.in_(list(unused))))
    db.commit()
    return {"carried": len(mapping), "kept": len(still_used), "removed": len(unused)}
