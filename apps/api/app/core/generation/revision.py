"""Versions of a lesson's slides and quiz. Every change keeps the version before it.

A lesson's current deck and quiz are its newest assets that no later version has
superseded (``pick_asset``). Regenerating, accepting a proposed change and editing each
create a new asset version and mark the previous one superseded, so any version can be
restored. Approved assets are never changed: the lesson is reopened first.

Proposed changes for single slides and questions wait on the current asset's content,
under ``proposals``, until the author accepts or discards them. Reviewer findings travel
with each new version, minus the blocks that changed, which are listed as changed since
the review instead.
"""
from __future__ import annotations

import copy
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.export.course import pick_asset
from app.models.asset import ApprovalState, Asset, AssetKind, Citation
from app.models.review import Review

PROPOSALS = "proposals"
_MARKER = re.compile(r"\[(\d{1,3})\]")
SLIDE_FIELDS = ("layout", "title", "bullets", "table", "notes")
QUESTION_FIELDS = ("stem", "options", "answer_index", "explanation")


class RevisionError(ValueError):
    """A change that cannot be made in the asset's current state."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def current(db: Session, lesson_id: str, kind: str) -> Asset | None:
    return pick_asset(list(db.scalars(select(Asset).where(Asset.lesson_id == lesson_id, Asset.kind == kind))), kind)


def next_version(db: Session, lesson_id: str) -> int:
    return (db.scalar(select(func.max(Asset.version)).where(Asset.lesson_id == lesson_id)) or 0) + 1


# ---- blocks -------------------------------------------------------------------
def blocks(kind: str, content: dict) -> dict[str, dict]:
    """Block id -> block: slides by their id, questions by their position ("0", "1", ...)."""
    if kind == AssetKind.SLIDES.value:
        return {s["id"]: s for s in content.get("slides", [])}
    return {str(i): q for i, q in enumerate(content.get("questions", []))}


def replace_block(kind: str, content: dict, block: str, value: dict) -> dict:
    """A copy of ``content`` with one block replaced; the slide id is kept."""
    out = copy.deepcopy(content)
    if kind == AssetKind.SLIDES.value:
        slides = out.get("slides", [])
        at = next((i for i, s in enumerate(slides) if s["id"] == block), None)
        if at is None:
            raise RevisionError(f"No slide {block} in this lesson")
        slides[at] = {**slides[at], **{k: value[k] for k in SLIDE_FIELDS if k in value}, "id": block}
    else:
        questions = out.get("questions", [])
        if not block.isdigit() or int(block) >= len(questions):
            raise RevisionError(f"No question {block} in this lesson")
        questions[int(block)] = {**questions[int(block)], **value}
    return out


def changed_blocks(kind: str, before: dict, after: dict) -> set[str]:
    fields = SLIDE_FIELDS if kind == AssetKind.SLIDES.value else QUESTION_FIELDS
    old, new = blocks(kind, before), blocks(kind, after)
    return {b for b in old.keys() | new.keys() if b not in old or b not in new or any(old[b].get(f) != new[b].get(f) for f in fields)}


# ---- citations ------------------------------------------------------------------
def slide_links(slides: list[dict], references: dict[str, dict]) -> list[tuple[str, str]]:
    """(slide id, chunk id) for every [n] marker that resolves through the deck's references."""
    links: list[tuple[str, str]] = []
    for s in slides:
        cells = [c for row in (s.get("table") or []) for c in row]
        seen: list[str] = []
        for n in _MARKER.findall(" ".join([s.get("title", ""), *s.get("bullets", []), *cells, s.get("notes", "")])):
            chunk = (references.get(n) or {}).get("chunk_id")
            if chunk and chunk not in seen:
                seen.append(chunk)
        links.extend((s["id"], c) for c in seen)
    return links


def deck_stats(slides: list[dict], references: dict[str, dict]) -> dict:
    markers, invalid, checked, uncited = 0, [], 0, 0
    for s in slides:
        cells = [c for row in (s.get("table") or []) for c in row]
        numbers = _MARKER.findall(" ".join([s.get("title", ""), *s.get("bullets", []), *cells, s.get("notes", "")]))
        markers += len(numbers)
        invalid += [int(n) for n in numbers if n not in references]
        if s.get("layout") not in ("title", "summary"):
            for b in s.get("bullets", []):
                checked += 1
                uncited += not _MARKER.search(b)
    return {"slides": len(slides), "citation_markers": markers, "invalid_citation_numbers": invalid, "bullets_checked": checked, "bullets_without_citation": uncited}


def citations_for(kind: str, content: dict) -> list[Citation]:
    if kind == AssetKind.SLIDES.value:
        return [Citation(block_id=b, chunk_id=c) for b, c in slide_links(content.get("slides", []), content.get("references", {}))]
    return [
        Citation(block_id=f"q{i}", chunk_id=q["chunk_id"], quote=q.get("source_span"))
        for i, q in enumerate(content.get("questions", []), 1)
        if q.get("chunk_id")
    ]


# ---- reviewer findings across versions --------------------------------------------
def carry_review(critique: dict | None, kind: str, changed: set[str]) -> dict | None:
    """Findings still true of the new version: those on unchanged blocks."""
    if not critique or "reviewer" not in critique or not changed:
        return copy.deepcopy(critique)
    out = copy.deepcopy(critique)
    review = out["reviewer"]
    section = "slides" if kind == AssetKind.SLIDES.value else "questions"
    for block in changed:
        review.get(section, {}).pop(block, None)
    review["changed"] = sorted(set(review.get("changed", [])) | changed)
    if review.get("rubric"):
        review["rubric_stale"] = True  # lesson-level scores describe the content before the change
    return out


# ---- versions -------------------------------------------------------------------------
def snapshot(db: Session, asset: Asset, content: dict, *, note: str, model: str | None = None, meta: dict | None = None,
             approval: str = ApprovalState.EDITED.value) -> Asset:
    """Save ``content`` as the asset's next version and supersede the current one."""
    if asset.approval == ApprovalState.APPROVED.value:
        raise RevisionError("This lesson is approved. Reopen it before changing it.")
    changed = changed_blocks(asset.kind, asset.content or {}, content)
    content = copy.deepcopy(content)
    # A waiting proposal for a block that just changed no longer applies to it.
    content[PROPOSALS] = [p for p in content.get(PROPOSALS, []) if p["block"] not in changed]
    if asset.kind == AssetKind.SLIDES.value:
        content["citation_stats"] = deck_stats(content.get("slides", []), content.get("references", {}))
    content["revision"] = {"note": note, "at": now_iso(), "from_version": asset.version, **(meta or {})}
    new = Asset(
        project_id=asset.project_id, lesson_id=asset.lesson_id, kind=asset.kind, version=next_version(db, asset.lesson_id),
        content=content, approval=approval, critique=carry_review(asset.critique, asset.kind, changed),
        generated_with_model=model or asset.generated_with_model, prompt_version_id=asset.prompt_version_id,
    )
    new.citations = citations_for(asset.kind, content)
    asset.superseded_at = datetime.now(UTC)
    db.add(new)
    db.flush()
    return new


def history(db: Session, lesson_id: str) -> list[Asset]:
    return list(db.scalars(
        select(Asset).where(Asset.lesson_id == lesson_id, Asset.kind.in_([AssetKind.SLIDES.value, AssetKind.QUIZ.value])).order_by(Asset.version.desc())
    ))


def restore(db: Session, lesson_id: str, asset_id: str) -> Asset:
    """Make an earlier version current again; the version it replaces stays in the history."""
    old = db.get(Asset, asset_id)
    if not old or old.lesson_id != lesson_id:
        raise RevisionError("That version is not part of this lesson")
    cur = current(db, lesson_id, old.kind)
    if cur and cur.id == old.id:
        return cur
    if cur and cur.approval == ApprovalState.APPROVED.value:
        raise RevisionError("This lesson is approved. Reopen it before restoring another version.")
    if cur:
        cur.superseded_at = datetime.now(UTC)
    old.superseded_at = None
    old.content = {**(old.content or {}), PROPOSALS: []}
    db.flush()
    return old


def set_approval(db: Session, lesson_id: str, approved: bool, actor_id: str) -> list[Asset]:
    """Approve or reopen a lesson: its current deck and quiz together."""
    assets = [a for a in (current(db, lesson_id, k) for k in (AssetKind.SLIDES.value, AssetKind.QUIZ.value)) if a]
    if not assets:
        raise RevisionError("This lesson has no generated content to approve")
    for a in assets:
        if approved:
            a.approval = ApprovalState.APPROVED.value
        elif a.approval == ApprovalState.APPROVED.value:
            a.approval = ApprovalState.EDITED.value if (a.content or {}).get("revision") else ApprovalState.GENERATED.value
        db.add(Review(reviewer_id=actor_id, target_type="asset", target_id=a.id, decision="approve" if approved else "reopen"))
    db.flush()
    return assets


# ---- proposed changes -------------------------------------------------------------------
def proposal(kind: str, block: str, before: dict, after: dict, *, reason: str, instructions: str, findings: list[str]) -> dict:
    return {
        "id": uuid.uuid4().hex[:12], "kind": "slide" if kind == AssetKind.SLIDES.value else "question", "block": block,
        "before": before, "after": after, "reason": reason, "instructions": instructions, "findings": findings, "created_at": now_iso(),
    }


def add_proposals(asset: Asset, new: list[dict]) -> None:
    """Attach proposals to the current asset; a newer proposal for a block replaces the older one."""
    if asset.approval == ApprovalState.APPROVED.value:
        raise RevisionError("This lesson is approved. Reopen it before changing it.")
    content = dict(asset.content or {})
    replaced = {p["block"] for p in new}
    content[PROPOSALS] = [p for p in content.get(PROPOSALS, []) if p["block"] not in replaced] + new
    asset.content = content  # reassign so SQLAlchemy persists the JSONB change


def accept_proposals(db: Session, asset: Asset, ids: list[str] | None) -> Asset:
    waiting = (asset.content or {}).get(PROPOSALS, [])
    chosen = [p for p in waiting if ids is None or p["id"] in ids]
    if not chosen:
        raise RevisionError("Those proposed changes are no longer waiting")
    content = copy.deepcopy(asset.content)
    for p in chosen:
        content = replace_block(asset.kind, content, p["block"], p["after"])
    content[PROPOSALS] = [p for p in waiting if p not in chosen]
    what = "change" if len(chosen) == 1 else "changes"
    return snapshot(db, asset, content, note=f"Accepted {len(chosen)} proposed {what}", meta={"accepted": [p["block"] for p in chosen]})


def discard_proposals(asset: Asset, ids: list[str] | None) -> int:
    content = dict(asset.content or {})
    waiting = content.get(PROPOSALS, [])
    content[PROPOSALS] = [p for p in waiting if ids is not None and p["id"] not in ids]
    asset.content = content
    return len(waiting) - len(content[PROPOSALS])


def edit_block(db: Session, asset: Asset, block: str, value: dict) -> Asset:
    """An author's own edit to one slide or question, saved as a new version."""
    if asset.kind == AssetKind.SLIDES.value:
        clean = {
            "title": str(value.get("title", "")).strip(),
            "bullets": [str(b).strip() for b in value.get("bullets", []) if str(b).strip()],
            "notes": str(value.get("notes", "")).strip(),
        }
        if not clean["title"]:
            raise RevisionError("A slide needs a title")
        label = f"Edited slide {block.lstrip('s')}"
    else:
        options = [str(o).strip() for o in value.get("options", [])]
        answer = value.get("answer_index")
        if not str(value.get("stem", "")).strip() or len(options) < 2 or not all(options) or not isinstance(answer, int) or not 0 <= answer < len(options):
            raise RevisionError("A question needs a stem, at least two options and one correct answer")
        clean = {"stem": str(value["stem"]).strip(), "options": options, "answer_index": answer, "explanation": str(value.get("explanation", "")).strip()}
        label = f"Edited question {int(block) + 1}"
    return snapshot(db, asset, replace_block(asset.kind, asset.content or {}, block, clean), note=label)
