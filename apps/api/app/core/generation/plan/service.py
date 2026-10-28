"""Course plan generation: sources -> objectives -> modules and lessons.

Single pass, no critique: this is the baseline the evaluation layer will later
be compared against. Two model calls (objectives, then a syllabus built on
them). Each lesson keeps the source chunks it was planned from so lesson
generation starts from the same evidence.

A rebuild can carry the author's instructions and intents (brief.py); they are appended
to both calls and kept on the new version's ``meta`` so the history says why it exists.
"""
from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.generation.brief import appendix, compose
from app.core.generation.evidence import evidence_budget, outline_chunks, pack, resolve_numbers
from app.core.jobs import service as jobs
from app.core.llm.client import chat_structured, llm_call_count
from app.core.prompts.service import get_active
from app.core.rag.retriever import citation_map, format_context
from app.models.course import CoursePlan, Lesson, Module, PlanStatus
from app.models.project import Project

log = logging.getLogger(__name__)

# Bounds laptop runtime: each lesson costs several model calls in the next step.
MAX_LESSONS = 8
# Plan context is an outline of everything, so each excerpt is kept short.
OUTLINE_CHARS_PER_CHUNK = 600

DEFAULT_AUDIENCE = "Professional learners new to the topic"
DEFAULT_DURATION = 60
DEFAULT_GOALS = "Cover the most important content in the sources."


class PlannedObjective(BaseModel):
    text: str = Field(description="Observable behaviour starting with a Bloom verb")
    bloom_level: str = Field(description="remember | understand | apply | analyze | evaluate | create")
    reference_numbers: list[int] = Field(default_factory=list, description="Reference numbers this objective is grounded in")


class ObjectiveSet(BaseModel):
    objectives: list[PlannedObjective] = Field(min_length=1, max_length=8)


class PlannedLesson(BaseModel):
    title: str
    estimated_minutes: int = Field(ge=1)
    objective_indexes: list[int] = Field(default_factory=list, description="Numbers of the objectives this lesson teaches, as listed")
    reference_numbers: list[int] = Field(default_factory=list, description="Reference numbers this lesson draws on")


class PlannedModule(BaseModel):
    title: str
    description: str = ""
    lessons: list[PlannedLesson] = Field(min_length=1)


class Syllabus(BaseModel):
    title: str = Field(description="Course title")
    summary: str = Field(description="Two or three sentences describing the course")
    modules: list[PlannedModule] = Field(min_length=1)


def build_plan_records(
    project_id: str,
    version: int,
    objectives: ObjectiveSet,
    syllabus: Syllabus,
    cmap: dict[int, str],
    source_of_chunk: dict[str, str],
) -> tuple[CoursePlan, dict]:
    """Turn the two model outputs into ORM records plus quality counters.

    Pure apart from constructing objects, so it is unit-testable without a database.
    """
    invalid_refs = 0
    objective_rows = []
    for i, o in enumerate(objectives.objectives, 1):
        chunk_ids, bad = resolve_numbers(o.reference_numbers, cmap)
        invalid_refs += len(bad)
        objective_rows.append({"id": f"O{i}", "text": o.text, "bloom_level": o.bloom_level, "source_chunk_ids": chunk_ids})
    valid_objective_ids = {row["id"] for row in objective_rows}

    plan = CoursePlan(
        project_id=project_id,
        version=version,
        title=syllabus.title[:512],
        summary=syllabus.summary,
        learning_objectives=objective_rows,
        status=PlanStatus.DRAFT.value,
    )

    lessons_kept = 0
    lessons_dropped = 0
    unknown_objectives = 0
    referenced: set[str] = {c for row in objective_rows for c in row["source_chunk_ids"]}
    for m_pos, m in enumerate(syllabus.modules, 1):
        module = Module(position=m_pos, title=m.title[:512], description=m.description or None)
        for l_pos, pl in enumerate(m.lessons, 1):
            if lessons_kept >= MAX_LESSONS:
                lessons_dropped += 1
                continue
            chunk_ids, bad = resolve_numbers(pl.reference_numbers, cmap)
            invalid_refs += len(bad)
            referenced.update(chunk_ids)
            objective_ids = [f"O{n}" for n in pl.objective_indexes if f"O{n}" in valid_objective_ids]
            unknown_objectives += len(pl.objective_indexes) - len(objective_ids)
            module.lessons.append(
                Lesson(
                    position=l_pos,
                    title=pl.title[:512],
                    estimated_minutes=pl.estimated_minutes,
                    objective_ids=objective_ids,
                    source_chunk_ids=chunk_ids,
                )
            )
            lessons_kept += 1
        if module.lessons:
            plan.modules.append(module)

    # Share of each source's offered excerpts the plan actually drew on.
    offered: dict[str, int] = {}
    used: dict[str, int] = {}
    for chunk_id in cmap.values():
        src = source_of_chunk[chunk_id]
        offered[src] = offered.get(src, 0) + 1
        if chunk_id in referenced:
            used[src] = used.get(src, 0) + 1
    plan.coverage = {src: round(used.get(src, 0) / n, 3) for src, n in offered.items()}

    stats = {
        "objectives": len(objective_rows),
        "modules": len(plan.modules),
        "lessons": lessons_kept,
        "lessons_dropped_over_cap": lessons_dropped,
        "invalid_reference_numbers": invalid_refs,
        "unknown_objective_links": unknown_objectives,
        "lessons_without_sources": sum(1 for mod in plan.modules for les in mod.lessons if not les.source_chunk_ids),
    }
    return plan, stats


async def generate_plan(db: Session, project_id: str, *, job_id: str | None = None, instructions: str | None = None,
                        intents: list[str] | None = None) -> dict:
    started = time.perf_counter()
    calls_before = llm_call_count()
    project = db.get(Project, project_id)
    if not project:
        raise ValueError(f"project {project_id} not found")
    outline = outline_chunks(db, project_id)
    if not outline:
        raise ValueError("No ready sources in this project. Upload and ingest documents first.")

    prompts = get_active(db, "plan")
    audience = project.target_audience or DEFAULT_AUDIENCE
    duration = str(project.duration_minutes or DEFAULT_DURATION)
    goals = project.learning_goals or DEFAULT_GOALS
    brief = compose(instructions, intents)

    # One context serves both calls so reference numbers mean the same thing in each.
    # Budget against the larger (syllabus) prompt, leaving room for the objectives list.
    syllabus_frame = prompts.render("syllabus", duration_minutes=duration, objectives="x" * 1600, audience=audience, rag_context="")
    budget = evidence_budget(prompts.system_prompt, syllabus_frame, schema=Syllabus)
    evidence = pack(outline, budget, max_chars_per_chunk=OUTLINE_CHARS_PER_CHUNK)
    context = format_context(evidence)
    cmap = citation_map(evidence)
    source_of_chunk = {c.chunk_id: c.source_id for c in evidence}
    log.info("plan context: %s of %s outline chunks within %s tokens", len(evidence), len(outline), budget)

    if job_id:
        jobs.progress(db, job_id, current=0, total=2, message=f"Drafting objectives from {len(evidence)} source excerpts")
    objectives = await chat_structured(
        prompts.system_prompt,
        prompts.render("objectives", audience=audience, duration_minutes=duration, goals=goals, rag_context=context) + appendix(brief),
        ObjectiveSet,
        temperature=0.3,
    )

    if job_id:
        if jobs.is_cancelled(db, job_id):
            return {"cancelled": True}
        jobs.progress(db, job_id, current=1, total=2, message="Building the syllabus")
    objectives_text = "\n".join(f"{i}. {o.text} ({o.bloom_level})" for i, o in enumerate(objectives.objectives, 1))
    syllabus = await chat_structured(
        prompts.system_prompt,
        prompts.render("syllabus", duration_minutes=duration, objectives=objectives_text, audience=audience, rag_context=context) + appendix(brief),
        Syllabus,
        temperature=0.3,
    )

    version = (db.scalar(select(func.max(CoursePlan.version)).where(CoursePlan.project_id == project_id)) or 0) + 1
    plan, stats = build_plan_records(project_id, version, objectives, syllabus, cmap, source_of_chunk)
    if not plan.modules:
        raise ValueError("The model returned a syllabus with no usable lessons.")
    plan.meta = {"note": "Rebuilt outline" if version > 1 else "Generated outline", "instructions": brief or None, "intents": intents or []}
    db.add(plan)
    db.commit()

    result = {
        "plan_id": plan.id,
        "version": version,
        **stats,
        "evidence_chunks": len(evidence),
        "outline_chunks": len(outline),
        "llm_calls": llm_call_count() - calls_before,
        "seconds": round(time.perf_counter() - started, 1),
        "prompt_version_id": prompts.version_id,
    }
    log.info("plan generated: %s", result)
    return result
