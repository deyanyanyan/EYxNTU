"""Course -> review requests for the trained reviewer.

Three kinds of request, each in the format of a task the reviewer was trained or
evaluated on:

* **Grounding**, one per slide: the slide's title, bullets, table and speaker notes,
  checked against the source passages its deck was generated from (RAGTruth format).
  The reviewer quotes every conflicting or unsupported span.
* **Rubric**, one per lesson and criterion (``criteria.py``): the whole deck scored 1-5,
  with the source passages as the reference (Prometheus format). This is prompted
  transfer from general rubrics, so it is advisory.
* **Distractors**, one per quiz question: how minimally different the options are,
  scored 1-5 (Oak format).

``ref`` in each request names the reviewed asset and block, so the import attaches every
finding to the slide or question it is about. Citation markers such as ``[2]`` are removed
from reviewed text; the reviewer was trained on plain responses.
"""
from __future__ import annotations

import re
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.export.course import pick_asset
from app.core.export.service import latest_plan
from app.core.review.criteria import CRITERIA, CRITERIA_VERSION
from app.models.asset import Asset, AssetKind
from app.models.chunk import Chunk
from app.models.project import Project

_MARKER = re.compile(r"\s*\[\d{1,3}\]")


def strip_markers(text: str) -> str:
    return _MARKER.sub("", text or "").strip()


def slide_text(slide: dict) -> str:
    lines = [strip_markers(slide.get("title", ""))]
    lines += [f"- {strip_markers(b)}" for b in slide.get("bullets") or []]
    lines += [" | ".join(strip_markers(c) for c in row) for row in slide.get("table") or []]
    if slide.get("notes"):
        lines.append(f"Speaker notes: {strip_markers(slide['notes'])}")
    return "\n".join(line for line in lines if line)


def deck_text(deck: dict) -> str:
    return "\n\n".join(f"Slide {i}: {slide_text(s)}" for i, s in enumerate(deck.get("slides", []), 1))


def source_context(lesson_title: str, audience: str, passages: list[tuple[str, str]]) -> str:
    head = f'Write lesson slides and speaker notes titled "{lesson_title}" for {audience}, using only the following source passages.'
    return head + "\n\n" + "\n\n".join(f"[{n}] {text.strip()}" for n, text in passages)


def lesson_requests(
    *, lesson_id: str, lesson_title: str, audience: str, objectives: list[str], deck_id: str | None, deck: dict | None,
    quiz_id: str | None, quiz: dict | None, passages: list[tuple[str, str]],
) -> list[dict]:
    """All review requests for one lesson. Pure: callers pass plain content dicts."""
    requests: list[dict] = []
    if deck and passages:
        context = source_context(lesson_title, audience, passages)
        for slide in deck.get("slides", []):
            requests.append({
                "id": f"{deck_id}|slide|{slide['id']}", "task": "ragtruth_grounding",
                "fields": {"context": context, "response": slide_text(slide)},
                "ref": {"asset_id": deck_id, "lesson_id": lesson_id, "kind": "slide", "block": slide["id"]},
            })
        teach = "; ".join(objectives) or lesson_title
        reference = "The source passages the lesson must teach:\n\n" + "\n\n".join(f"[{n}] {text.strip()}" for n, text in passages)
        for c in CRITERIA:
            requests.append({
                "id": f"{deck_id}|rubric|{c['id']}", "task": "prometheus_rubric",
                "fields": {
                    "instruction": f'Create a short lesson titled "{lesson_title}" for {audience}. It must teach: {teach}.',
                    "response": deck_text(deck), "reference": reference, "criteria": c["criteria"],
                    **{f"score{i}": c[f"score{i}"] for i in range(1, 6)},
                },
                "ref": {"asset_id": deck_id, "lesson_id": lesson_id, "kind": "rubric", "block": c["id"], "criterion": c["name"]},
            })
    for i, q in enumerate((quiz or {}).get("questions", [])):
        options, answer = q.get("options", []), q.get("answer_index")
        if answer is None or not 0 <= answer < len(options):
            continue
        requests.append({
            "id": f"{quiz_id}|question|{i}", "task": "oak_distractors",
            "fields": {"question": q["stem"], "answer": options[answer], "distractors": [o for j, o in enumerate(options) if j != answer]},
            "ref": {"asset_id": quiz_id, "lesson_id": lesson_id, "kind": "question", "block": str(i)},
        })
    return requests


def build_requests(db: Session, project_id: str) -> tuple[list[dict], dict]:
    plan = latest_plan(db, project_id)
    if plan is None:
        raise ValueError("This project has no course plan to review.")
    project = db.get(Project, project_id)
    audience = (project.target_audience if project else None) or "the course's learners"
    objective_text = {o.get("id"): o.get("text", "") for o in plan.learning_objectives or []}
    requests: list[dict] = []
    reviewed: dict[str, int] = {}
    for module in plan.modules:
        for lesson in module.lessons:
            assets = list(db.scalars(select(Asset).where(Asset.lesson_id == lesson.id)))
            deck = pick_asset(assets, AssetKind.SLIDES.value)
            quiz = pick_asset(assets, AssetKind.QUIZ.value)
            refs = sorted(((deck.content or {}).get("references") or {}).items(), key=lambda kv: int(kv[0])) if deck else []
            chunk_ids = [r["chunk_id"] for _, r in refs if r.get("chunk_id")]
            texts = {c.id: c.text for c in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))} if chunk_ids else {}
            passages = [(n, texts[r["chunk_id"]]) for n, r in refs if r.get("chunk_id") in texts]
            requests += lesson_requests(
                lesson_id=lesson.id, lesson_title=lesson.title, audience=audience,
                objectives=[objective_text[i] for i in lesson.objective_ids or [] if objective_text.get(i)],
                deck_id=deck.id if deck else None, deck=deck.content if deck else None,
                quiz_id=quiz.id if quiz else None, quiz=quiz.content if quiz else None, passages=passages,
            )
            reviewed |= {a.id: a.version for a in (deck, quiz) if a}
    manifest = {
        "project_id": project_id, "plan_id": plan.id, "plan_version": plan.version, "criteria_version": CRITERIA_VERSION,
        "requests": len(requests), "assets": reviewed, "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    return requests, manifest
