"""Quiz generation with a generate -> validate -> fix loop.

Every question must quote a verbatim `source_span` from the retrieved context;
the validator rejects questions whose span is not found in the context (the
cheapest possible hallucination check) and questions that leak the answer in
the stem. Failed questions get one repair attempt, then are dropped.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.llm.client import chat_structured
from app.core.prompts.service import PromptSet
from app.core.rag.retriever import RetrievedChunk, citation_map, format_context

log = logging.getLogger(__name__)


class RawQuestion(BaseModel):
    stem: str = Field(description="The question. Must not contain or paraphrase the correct answer.")
    correct_answer: str
    distractors: list[str] = Field(min_length=3, max_length=3, description="Plausible, same category, similar length to the correct answer")
    explanation: str = Field(description="Why the correct answer is right, citing the reference number like [2]")
    source_span: str = Field(description="VERBATIM sentence or table row copied from the references that supports the answer")
    reference: int = Field(description="Reference number the source_span was copied from")
    difficulty: str = Field(description="easy | medium | hard")


class RawQuestionBatch(BaseModel):
    questions: list[RawQuestion]


@dataclass
class ValidationIssue:
    code: str
    detail: str


def validate(q: RawQuestion, context: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    norm_ctx = " ".join(context.split()).lower()
    span = " ".join(q.source_span.split()).lower()
    if len(span) < 15 or span not in norm_ctx:
        issues.append(ValidationIssue("span_not_found", "source_span is not verbatim from the references"))
    if q.correct_answer.lower().strip() in q.stem.lower():
        issues.append(ValidationIssue("answer_leak", "stem contains the correct answer"))
    if len({q.correct_answer.strip().lower(), *[d.strip().lower() for d in q.distractors]}) < 4:
        issues.append(ValidationIssue("duplicate_options", "options are not distinct"))
    lens = [len(q.correct_answer)] + [len(d) for d in q.distractors]
    if max(lens) > 2.5 * max(1, min(lens)):
        issues.append(ValidationIssue("length_giveaway", "answer length differs markedly from distractors"))
    return issues


class FixedQuestion(BaseModel):
    question: RawQuestion


async def generate_quiz(
    chunks: list[RetrievedChunk],
    *,
    prompts: PromptSet,
    count: int = 5,
    difficulty_mix: str = "2 easy, 2 medium, 1 hard",
    objectives: str = "",
    existing_stems: list[str] | None = None,
    auto_fix: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Return (accepted_questions, rejected_with_reasons). Each accepted question carries `chunk_id`."""
    context = format_context(chunks)
    cmap = citation_map(chunks)
    existing = "\n".join(f"- {s}" for s in (existing_stems or [])[:15])

    batch = await chat_structured(
        prompts.system_prompt,
        prompts.render("generate", rag_context=context, count=str(count), difficulty_mix=difficulty_mix, objectives=objectives, existing=existing),
        RawQuestionBatch,
        temperature=0.6,
    )

    accepted: list[dict] = []
    rejected: list[dict] = []
    for q in batch.questions:
        issues = validate(q, context)
        if issues and auto_fix:
            try:
                fixed = await chat_structured(
                    prompts.system_prompt,
                    prompts.render("fix", rag_context=context, question=q.model_dump_json(indent=2), issues="\n".join(f"- {i.code}: {i.detail}" for i in issues)),
                    FixedQuestion,
                    temperature=0.4,
                )
                q = fixed.question
                issues = validate(q, context)
            except Exception as exc:  # pragma: no cover
                log.warning("fix failed: %s", exc)
        if issues:
            rejected.append({"question": q.model_dump(), "issues": [i.__dict__ for i in issues]})
            continue
        options = [q.correct_answer, *q.distractors]
        random.shuffle(options)
        accepted.append(
            {
                "stem": q.stem,
                "options": options,
                "answer_index": options.index(q.correct_answer),
                "explanation": q.explanation,
                "difficulty": q.difficulty,
                "source_span": q.source_span,
                "chunk_id": cmap.get(q.reference),
            }
        )
    log.info("quiz: %s accepted, %s rejected", len(accepted), len(rejected))
    return accepted, rejected
