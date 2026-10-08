"""Batch scoring for saved course bundles; it never affects generation state."""
from __future__ import annotations

import statistics
from typing import Any

from app.core.evaluation.checks import evaluate_course_overlap, evaluate_lesson
from app.core.generation.critique.service import score_dimensions
from app.core.llm.client import LLMCallTrace, LLMTarget, collect_llm_calls
from app.core.prompts.service import PromptSet


def _evidence_context(lesson: dict[str, Any]) -> str:
    sections: list[str] = []
    for label, asset_key in (("SLIDE REFERENCES", "slides"), ("QUIZ REFERENCES", "quiz")):
        references = (lesson.get("evidence") or {}).get(asset_key) or {}
        lines = [f"[{number}] {ref.get('source_name') or 'source'} | {ref.get('heading_path') or ''}\n{ref.get('text') or '[reference text missing]'}" for number, ref in references.items()]
        if lines:
            sections.append(f"=== {label} ===\n" + "\n\n".join(lines))
    return "\n\n".join(sections)


def _judge_content(lesson: dict[str, Any]) -> dict[str, Any]:
    slides = (lesson.get("slides") or {}).get("content") or {}
    quiz = (lesson.get("quiz") or {}).get("content") or {}
    return {
        "lesson_title": (lesson.get("lesson") or {}).get("title"),
        "slides": slides.get("slides") or [],
        "quiz_questions": quiz.get("questions") or [],
    }


def _objectives(bundle: dict[str, Any], lesson: dict[str, Any]) -> str:
    by_id = {item.get("id"): item for item in (bundle.get("course", {}).get("plan", {}).get("learning_objectives") or [])}
    ids = (lesson.get("lesson") or {}).get("objective_ids") or []
    selected = [by_id[item_id] for item_id in ids if item_id in by_id]
    return "\n".join(f"- {item.get('text', '')}" for item in selected)


async def score_bundle(
    bundle: dict[str, Any],
    *,
    prompts: PromptSet,
    prompt_hash: str,
    target: LLMTarget | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Score all saved lesson bundles. Missing judge config means deterministic-only."""
    manifest = bundle.get("manifest") or {}
    course = bundle.get("course") or {}
    lessons = course.get("lessons") or []
    brief = manifest.get("brief") or {}
    results: list[dict[str, Any]] = []
    check_results: list[dict[str, Any]] = []

    for lesson in lessons:
        checks = evaluate_lesson(lesson)
        check_results.append(checks)
        judge_result: dict[str, Any] = {
            "status": "not_requested" if target is None else "scored",
            "model": target.model if target else None,
            "prompt_sha256": prompt_hash if target else None,
            "same_model_endpoint_as_generator": bool(
                target
                and target.model == (manifest.get("generator") or {}).get("model")
                and target.base_url.rstrip("/") == (manifest.get("generator") or {}).get("base_url", "").rstrip("/")
            ),
            "dimensions": {},
            "dimension_errors": {},
            "usage": None,
        }
        if target:
            trace = LLMCallTrace()
            with collect_llm_calls(trace):
                scores, errors = await score_dimensions(
                    _judge_content(lesson),
                    _evidence_context(lesson),
                    audience=str(brief.get("audience") or ""),
                    objectives=_objectives(bundle, lesson),
                    prompts=prompts,
                    target=target,
                )
            judge_result["dimensions"] = {name: score.model_dump() for name, score in scores.items()}
            judge_result["dimension_errors"] = errors
            judge_result["status"] = "scored" if scores and not errors else "partial" if scores else "error"
            judge_result["usage"] = trace.summary()
        results.append({
            "score_version": 1,
            "run_id": manifest.get("run_id"),
            "generator": manifest.get("generator") or {},
            "generation": manifest.get("generation") or {},
            "lesson_id": checks.get("lesson_id"),
            "title": checks.get("title"),
            "checks": checks,
            "judge": judge_result,
        })

    overlap = evaluate_course_overlap(lessons)
    check_totals: dict[str, Any] = {}
    rejection_totals: dict[str, int] = {}
    for row in check_results:
        for name, value in (row.get("counts") or {}).items():
            if name == "quiz_rejections_by_code":
                for code, count in value.items():
                    rejection_totals[code] = rejection_totals.get(code, 0) + int(count)
            elif isinstance(value, int):
                check_totals[name] = check_totals.get(name, 0) + value
    check_totals["quiz_rejections_by_code"] = rejection_totals
    course_result = {
        "score_version": 1,
        "run_id": manifest.get("run_id"),
        "generator": manifest.get("generator") or {},
        "generation": manifest.get("generation") or {},
        "lessons_scored": len(results),
        "judge_means": score_means(results),
        "judge_lesson_score_stddev": score_stddevs(results),
        "check_totals": check_totals,
        "course_overlap": overlap,
    }
    return results, course_result


def score_means(results: list[dict[str, Any]]) -> dict[str, float | None]:
    values: dict[str, list[float]] = {name: [] for name in ("grounding", "coherence", "pedagogy")}
    for row in results:
        for name, dimension in (row.get("judge") or {}).get("dimensions", {}).items():
            if name in values:
                values[name].append(float(dimension["score"]))
    return {name: round(sum(scores) / len(scores), 3) if scores else None for name, scores in values.items()}


def score_stddevs(results: list[dict[str, Any]]) -> dict[str, float | None]:
    """Population standard deviation across lessons in one run, not run variance."""
    values: dict[str, list[float]] = {name: [] for name in ("grounding", "coherence", "pedagogy")}
    for row in results:
        for name, dimension in (row.get("judge") or {}).get("dimensions", {}).items():
            if name in values:
                values[name].append(float(dimension["score"]))
    return {
        name: round(statistics.pstdev(scores), 3) if scores else None
        for name, scores in values.items()
    }
