"""Lesson asset generation: approved plan -> slide deck + quiz per lesson.

Single pass, no critique: the baseline. Each lesson gets evidence from the
chunks the planner assigned to it plus a retrieval pass on its title and
objectives, then one deck call and one quiz call (the quiz generator keeps its
existing validate-and-repair loop). Failures are recorded per lesson rather than
aborting the course, because the failure rate is itself a baseline number.
"""
from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.generation.evidence import chunks_by_id, dedupe, evidence_budget, extract_citations, pack, reference_table
from app.core.generation.quiz.service import RawQuestionBatch, generate_quiz
from app.core.jobs import service as jobs
from app.core.llm.client import chat_structured, llm_call_count
from app.core.prompts.service import PromptSet, get_active
from app.core.rag.retriever import RetrievedChunk, citation_map, format_context, retrieve
from app.models.asset import ApprovalState, Asset, AssetKind, Citation
from app.models.course import CoursePlan, Lesson, Module, PlanStatus
from app.models.project import Project

log = logging.getLogger(__name__)

# Kept small so a lesson finishes within the request timeout on a CPU laptop.
SLIDE_COUNT = "5-7"
QUIZ_QUESTIONS = 3
QUIZ_DIFFICULTY = "1 easy, 1 medium, 1 hard"
RETRIEVAL_TOP_K = 8


class Slide(BaseModel):
    id: str
    layout: str = Field(description="title | bullets | two_column | table | example | summary")
    title: str
    bullets: list[str] = Field(default_factory=list, description="At most 5 bullets; factual bullets end with a citation marker like [2]")
    table: list[list[str]] | None = Field(default=None, description="Rows of cells, first row is the header")
    notes: str = Field(default="", description="Speaker notes in plain prose")


class Deck(BaseModel):
    slides: list[Slide] = Field(min_length=3, max_length=14)


def latest_approved_plan(db: Session, project_id: str) -> CoursePlan | None:
    plan = db.scalar(select(CoursePlan).where(CoursePlan.project_id == project_id).order_by(CoursePlan.version.desc()).limit(1))
    return plan if plan and plan.status == PlanStatus.APPROVED.value else None


def ordered_lessons(db: Session, plan_id: str) -> list[Lesson]:
    return list(
        db.scalars(select(Lesson).join(Module, Module.id == Lesson.module_id).where(Module.plan_id == plan_id).order_by(Module.position, Lesson.position))
    )


def objectives_for(plan: CoursePlan, lesson: Lesson) -> str:
    by_id = {o["id"]: o for o in plan.learning_objectives}
    chosen = [by_id[i] for i in lesson.objective_ids if i in by_id] or plan.learning_objectives
    return "\n".join(f"- {o['text']}" for o in chosen)


def normalise_deck(deck: Deck, cmap: dict[int, str]) -> tuple[list[dict], list[tuple[str, str]], dict]:
    """Stable slide ids, per-slide citations, and citation quality counters.

    Ids are reassigned as s1..sn: the model's own ids are often duplicated or
    missing, and citations and future review comments anchor on them.
    """
    slides: list[dict] = []
    links: list[tuple[str, str]] = []
    markers = 0
    invalid: list[int] = []
    factual_bullets = 0
    uncited_bullets = 0
    for i, s in enumerate(deck.slides, 1):
        slide_id = f"s{i}"
        cells = [cell for row in (s.table or []) for cell in row]
        cited = extract_citations(" ".join([s.title, *s.bullets, *cells, s.notes]), cmap)
        markers += cited.marker_count
        invalid.extend(cited.invalid_numbers)
        links.extend((slide_id, chunk_id) for chunk_id in cited.chunk_ids)
        if s.layout not in ("title", "summary"):
            for b in s.bullets:
                factual_bullets += 1
                if not extract_citations(b, cmap).marker_count:
                    uncited_bullets += 1
        slides.append({"id": slide_id, "layout": s.layout, "title": s.title, "bullets": s.bullets, "table": s.table, "notes": s.notes})
    stats = {
        "slides": len(slides),
        "citation_markers": markers,
        "invalid_citation_numbers": invalid,
        "bullets_checked": factual_bullets,
        "bullets_without_citation": uncited_bullets,
    }
    return slides, links, stats


def lesson_evidence(db: Session, project_id: str, lesson: Lesson, objectives: str, budget: int) -> list[RetrievedChunk]:
    planned = chunks_by_id(db, list(lesson.source_chunk_ids or []))
    retrieved = retrieve(db, project_id, f"{lesson.title}\n{objectives}", top_k=RETRIEVAL_TOP_K)
    return pack(dedupe(planned, retrieved), budget)


def _replace_generated_assets(db: Session, lesson_id: str) -> int:
    """Remove this lesson's unapproved assets; approved ones are never overwritten.

    Committed immediately: a later rollback after a failed deck or quiz call
    must not resurrect the old assets alongside the new ones.
    """
    version = db.scalar(select(func.max(Asset.version)).where(Asset.lesson_id == lesson_id)) or 0
    db.execute(delete(Asset).where(Asset.lesson_id == lesson_id, Asset.approval != ApprovalState.APPROVED.value))
    db.commit()
    return version + 1


async def _generate_deck(plan: CoursePlan, lesson: Lesson, project: Project, objectives: str, evidence: list[RetrievedChunk], prompts: PromptSet) -> tuple[dict, list[tuple[str, str]], dict]:
    cmap = citation_map(evidence)
    deck = await chat_structured(
        prompts.system_prompt,
        prompts.render(
            "deck",
            lesson_title=lesson.title,
            estimated_minutes=str(lesson.estimated_minutes or 10),
            objectives=objectives,
            audience=project.target_audience or "Professional learners new to the topic",
            rag_context=format_context(evidence),
            slide_count=SLIDE_COUNT,
        ),
        Deck,
        temperature=0.4,
    )
    slides, links, stats = normalise_deck(deck, cmap)
    return {"slides": slides, "references": reference_table(evidence), "citation_stats": stats}, links, stats


async def generate_lesson(db: Session, project: Project, plan: CoursePlan, lesson: Lesson, deck_prompts: PromptSet, quiz_prompts: PromptSet) -> dict:
    started = time.perf_counter()
    objectives = objectives_for(plan, lesson)
    deck_frame = deck_prompts.render(
        "deck", lesson_title=lesson.title, estimated_minutes="10", objectives=objectives,
        audience=project.target_audience or "", rag_context="", slide_count=SLIDE_COUNT,
    )
    budget = evidence_budget(deck_prompts.system_prompt, deck_frame, schema=Deck)
    evidence = lesson_evidence(db, project.id, lesson, objectives, budget)
    outcome: dict = {"lesson_id": lesson.id, "title": lesson.title, "evidence_chunks": len(evidence), "errors": []}
    if not evidence:
        outcome["errors"].append("no evidence retrieved for this lesson")
        return outcome

    version = _replace_generated_assets(db, lesson.id)
    common = {"project_id": project.id, "lesson_id": lesson.id, "version": version, "generated_with_model": settings.llm_model}

    try:
        content, links, stats = await _generate_deck(plan, lesson, project, objectives, evidence, deck_prompts)
        asset = Asset(kind=AssetKind.SLIDES.value, content=content, prompt_version_id=deck_prompts.version_id, **common)
        asset.citations = [Citation(block_id=slide_id, chunk_id=chunk_id) for slide_id, chunk_id in links]
        db.add(asset)
        db.commit()
        outcome["slides"] = stats
    except Exception as exc:
        db.rollback()
        log.warning("deck failed for lesson %s: %s", lesson.id, exc)
        outcome["errors"].append(f"slides: {type(exc).__name__}: {str(exc)[:300]}")

    try:
        # The quiz prompt is shorter than the deck prompt, so the same evidence fits.
        quiz_budget = evidence_budget(quiz_prompts.system_prompt, quiz_prompts.render("generate", rag_context=""), schema=RawQuestionBatch)
        quiz_evidence = pack(evidence, quiz_budget)
        accepted, rejected = await generate_quiz(
            quiz_evidence, prompts=quiz_prompts, count=QUIZ_QUESTIONS, difficulty_mix=QUIZ_DIFFICULTY, objectives=objectives,
        )
        asset = Asset(
            kind=AssetKind.QUIZ.value,
            content={"questions": accepted, "rejected": rejected, "references": reference_table(quiz_evidence)},
            prompt_version_id=quiz_prompts.version_id,
            **common,
        )
        asset.citations = [
            Citation(block_id=f"q{i}", chunk_id=q["chunk_id"], quote=q["source_span"])
            for i, q in enumerate(accepted, 1)
            if q.get("chunk_id")
        ]
        db.add(asset)
        db.commit()
        outcome["quiz"] = {"accepted": len(accepted), "rejected": len(rejected)}
    except Exception as exc:
        db.rollback()
        log.warning("quiz failed for lesson %s: %s", lesson.id, exc)
        outcome["errors"].append(f"quiz: {type(exc).__name__}: {str(exc)[:300]}")

    outcome["seconds"] = round(time.perf_counter() - started, 1)
    return outcome


async def generate_lessons(db: Session, project_id: str, *, job_id: str | None = None) -> dict:
    started = time.perf_counter()
    calls_before = llm_call_count()
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"project {project_id} not found")
    plan = latest_approved_plan(db, project_id)
    if not plan:
        raise ValueError("The latest course plan is not approved. Approve it before generating lessons.")
    lessons = ordered_lessons(db, plan.id)
    deck_prompts = get_active(db, "slides")
    quiz_prompts = get_active(db, "quiz")

    outcomes: list[dict] = []
    cancelled = False
    for i, lesson in enumerate(lessons):
        if job_id:
            if jobs.is_cancelled(db, job_id):
                cancelled = True
                break
            jobs.progress(db, job_id, current=i, total=len(lessons), message=f"Lesson {i + 1} of {len(lessons)}: {lesson.title}")
        outcomes.append(await generate_lesson(db, project, plan, lesson, deck_prompts, quiz_prompts))

    produced = sum(1 for o in outcomes for k in ("slides", "quiz") if k in o)
    if not cancelled and lessons and produced == 0:
        first = next((e for o in outcomes for e in o["errors"]), "unknown error")
        raise RuntimeError(f"No lesson assets could be generated. First error: {first}")

    slide_stats = [o["slides"] for o in outcomes if "slides" in o]
    result = {
        "plan_id": plan.id,
        "lessons": len(lessons),
        "lessons_attempted": len(outcomes),
        "cancelled": cancelled,
        "decks": len(slide_stats),
        "quizzes": sum(1 for o in outcomes if "quiz" in o),
        "slides": sum(s["slides"] for s in slide_stats),
        "questions_accepted": sum(o["quiz"]["accepted"] for o in outcomes if "quiz" in o),
        "questions_rejected": sum(o["quiz"]["rejected"] for o in outcomes if "quiz" in o),
        "invalid_citation_numbers": sum(len(s["invalid_citation_numbers"]) for s in slide_stats),
        "bullets_checked": sum(s["bullets_checked"] for s in slide_stats),
        "bullets_without_citation": sum(s["bullets_without_citation"] for s in slide_stats),
        "errors": [f"{o['title']}: {e}" for o in outcomes for e in o["errors"]],
        "llm_calls": llm_call_count() - calls_before,
        "seconds": round(time.perf_counter() - started, 1),
        "per_lesson": outcomes,
    }
    log.info("lessons generated: %s", {k: v for k, v in result.items() if k != "per_lesson"})
    return result
