"""Targeted changes: proposals for single slides and questions.

A slide or question is rewritten against the same numbered references its lesson was
generated from (stored with the deck and quiz), so citation markers keep their meaning.
Fixes use the reviewer's findings as instructions (brief.py). Results wait as proposals
(revision.py) for the author to accept or discard; nothing here changes a lesson's
current content.
"""
from __future__ import annotations

import json
import logging
import random

from sqlalchemy.orm import Session

from app.core.generation import revision
from app.core.generation.brief import compose, flagged_blocks, question_findings, slide_findings
from app.core.generation.evidence import chunks_by_id
from app.core.generation.lesson.service import Slide
from app.core.generation.quiz.service import FixedQuestion, RawQuestion, validate
from app.core.jobs import service as jobs
from app.core.llm.client import chat_structured, llm_call_count
from app.core.prompts.service import PromptSet, get_active
from app.core.rag.retriever import RetrievedChunk
from app.models.asset import ApprovalState, Asset, AssetKind
from app.models.course import CoursePlan, Lesson, Module
from app.models.project import Project

log = logging.getLogger(__name__)

# ---- the references an asset was generated from ----------------------------------------
def numbered_references(db: Session, references: dict[str, dict]) -> tuple[str, dict[int, str]]:
    """The asset's references with their original numbers, for a prompt and its citation map.

    Passages that no longer exist (their source was deleted) are left out; their numbers
    stay unused rather than shifting the others.
    """
    order = sorted(((int(n), r["chunk_id"]) for n, r in references.items() if r.get("chunk_id")))
    loaded: dict[str, RetrievedChunk] = {c.chunk_id: c for c in chunks_by_id(db, [cid for _, cid in order])}
    parts, cmap = [], {}
    for n, cid in order:
        c = loaded.get(cid)
        if not c:
            continue
        loc = c.source_name + (f" › {c.heading_path}" if c.heading_path else "")
        parts.append(f"[{n}] {loc}\n{c.text}")
        cmap[n] = cid
    return "\n\n".join(parts), cmap


def _lesson_context(db: Session, lesson: Lesson) -> tuple[CoursePlan, Project, str]:
    module = db.get(Module, lesson.module_id)
    plan = db.get(CoursePlan, module.plan_id)
    project = db.get(Project, plan.project_id)
    by_id = {o["id"]: o for o in plan.learning_objectives or []}
    chosen = [by_id[i] for i in lesson.objective_ids or [] if i in by_id] or plan.learning_objectives or []
    return plan, project, "\n".join(f"- {o['text']}" for o in chosen)


async def rewrite_slide(db: Session, deck: Asset, block: str, brief: str, prompts: PromptSet) -> dict:
    lesson = db.get(Lesson, deck.lesson_id)
    _, project, objectives = _lesson_context(db, lesson)
    content = deck.content or {}
    slides = revision.blocks(AssetKind.SLIDES.value, content)
    if block not in slides:
        raise revision.RevisionError(f"No slide {block} in this lesson")
    context, _ = numbered_references(db, content.get("references", {}))
    others = "\n".join(f"- {s['title']}: " + "; ".join(s.get("bullets", [])[:3]) for b, s in slides.items() if b != block) or "(none)"
    out = await chat_structured(
        prompts.system_prompt,
        prompts.render(
            "slide", lesson_title=lesson.title, objectives=objectives, audience=project.target_audience or "Professional learners new to the topic",
            other_slides=others, slide=json.dumps({k: slides[block].get(k) for k in ("id", *revision.SLIDE_FIELDS)}, ensure_ascii=False, indent=2),
            instructions=brief or "Improve the slide while keeping its purpose.", rag_context=context,
        ),
        Slide,
        temperature=0.4,
    )
    return {"id": block, "layout": out.layout, "title": out.title, "bullets": out.bullets, "table": out.table, "notes": out.notes}


async def rewrite_question(db: Session, quiz: Asset, block: str, brief: str, prompts: PromptSet, *, options_only: bool) -> dict:
    lesson = db.get(Lesson, quiz.lesson_id)
    _, _, objectives = _lesson_context(db, lesson)
    content = quiz.content or {}
    questions = revision.blocks(AssetKind.QUIZ.value, content)
    if block not in questions:
        raise revision.RevisionError(f"No question {int(block) + 1} in this lesson")
    q = questions[block]
    context, cmap = numbered_references(db, content.get("references", {}))
    answer = q["options"][q["answer_index"]]
    current = {
        "stem": q["stem"], "correct_answer": answer, "distractors": [o for i, o in enumerate(q["options"]) if i != q["answer_index"]],
        "explanation": q.get("explanation", ""), "source_span": q.get("source_span", ""),
        "reference": next((n for n, cid in cmap.items() if cid == q.get("chunk_id")), 1), "difficulty": q.get("difficulty", "medium"),
    }
    raw = await chat_structured(
        prompts.system_prompt,
        prompts.render("rewrite", objectives=objectives, question=json.dumps(current, ensure_ascii=False, indent=2),
                       instructions=brief or "Improve the question while testing the same concept.", rag_context=context),
        RawQuestion,
        temperature=0.5,
    )
    if options_only:  # only the distractors may change
        raw = raw.model_copy(update={k: current[k] for k in ("stem", "correct_answer", "explanation", "source_span", "reference", "difficulty")})
    issues = validate(raw, context)
    if issues:
        fixed = await chat_structured(
            prompts.system_prompt,
            prompts.render("fix", rag_context=context, question=raw.model_dump_json(indent=2), issues="\n".join(f"- {i.code}: {i.detail}" for i in issues)),
            FixedQuestion,
            temperature=0.4,
        )
        raw = fixed.question
        issues = validate(raw, context)
    if issues:
        raise revision.RevisionError("; ".join(i.detail for i in issues))
    options = [raw.correct_answer, *raw.distractors]
    random.shuffle(options)
    return {
        "stem": raw.stem, "options": options, "answer_index": options.index(raw.correct_answer), "explanation": raw.explanation,
        "difficulty": raw.difficulty, "source_span": raw.source_span, "chunk_id": cmap.get(raw.reference) or q.get("chunk_id"),
    }


# ---- the job ----------------------------------------------------------------------------
async def propose(db: Session, project_id: str, *, targets: list[dict], lesson_ids: list[str], fix: bool,
                  instructions: str | None, intents: list[str], job_id: str | None = None) -> dict:
    """Proposals for explicit targets ({lesson_id, kind, block}) and, with ``fix``, for every
    flagged slide and question in ``lesson_ids``."""
    calls_before = llm_call_count()
    work: list[tuple[Asset, str]] = []
    for t in targets:
        asset = revision.current(db, t["lesson_id"], AssetKind.SLIDES.value if t["kind"] == "slide" else AssetKind.QUIZ.value)
        if asset and asset.project_id == project_id:
            work.append((asset, str(t["block"])))
    for lesson_id in lesson_ids if fix else []:
        deck, quiz = revision.current(db, lesson_id, AssetKind.SLIDES.value), revision.current(db, lesson_id, AssetKind.QUIZ.value)
        work += [w for w in flagged_blocks(deck, quiz) if w not in work and w[0].project_id == project_id]
    if not work:
        raise ValueError("Nothing to change: the selection has no slides or questions that need it.")

    slide_prompts, quiz_prompts = get_active(db, "slides"), get_active(db, "quiz")
    made, failed, skipped = 0, [], 0
    for i, (asset, block) in enumerate(work):
        if job_id:
            if jobs.is_cancelled(db, job_id):
                break
            label = f"slide {block.lstrip('s')}" if asset.kind == AssetKind.SLIDES.value else f"question {int(block) + 1}"
            jobs.progress(db, job_id, current=i, total=len(work), message=f"Rewriting {label} of “{db.get(Lesson, asset.lesson_id).title}”")
        if asset.approval == ApprovalState.APPROVED.value:
            skipped += 1
            continue
        findings = (slide_findings if asset.kind == AssetKind.SLIDES.value else question_findings)(asset.critique, block) if fix or "fix" in intents else []
        brief = compose(instructions, intents, findings)
        try:
            if asset.kind == AssetKind.SLIDES.value:
                after = await rewrite_slide(db, asset, block, brief, slide_prompts)
            else:
                options_only = bool(findings) and not instructions and not [x for x in intents if x != "fix"]
                after = await rewrite_question(db, asset, block, brief, quiz_prompts, options_only=options_only)
            before = revision.blocks(asset.kind, asset.content or {})[block]
            revision.add_proposals(asset, [revision.proposal(asset.kind, block, before, after, reason="fix" if findings else "regenerate",
                                                             instructions=brief, findings=findings)])
            db.commit()
            made += 1
        except Exception as exc:
            db.rollback()
            log.warning("proposal failed for %s %s: %s", asset.id, block, exc)
            failed.append(f"{block}: {type(exc).__name__}: {str(exc)[:200]}")
    if not made and failed:
        raise RuntimeError(f"No change could be prepared. First error: {failed[0]}")
    return {"proposals": made, "failed": failed, "skipped_approved": skipped, "targets": len(work), "llm_calls": llm_call_count() - calls_before}
