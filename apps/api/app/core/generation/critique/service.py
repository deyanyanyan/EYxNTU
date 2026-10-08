"""Agentic critique of a generated asset.

Three rubric dimensions are scored in parallel (grounding, coherence, pedagogy),
then a summary call merges the feedback into concrete revision instructions.
Prompts come from the active "critique" PromptSet and are substituted with:
  {content}      the asset as JSON/markdown
  {rag_context}  the retrieved source references the asset should rest on
  {audience} {objectives}
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.llm.client import LLMTarget, chat_structured
from app.core.prompts.service import PromptSet, get_active


class DimensionScore(BaseModel):
    score: int = Field(ge=0, le=5)
    feedback: str
    issues: list[str] = Field(default_factory=list)


class CritiqueSummary(BaseModel):
    overall_score: float = Field(ge=0, le=5)
    revise: bool
    revision_instructions: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


@dataclass
class CritiqueResult:
    grounding: DimensionScore
    coherence: DimensionScore
    pedagogy: DimensionScore
    summary: CritiqueSummary
    prompt_version_id: str | None

    def as_dict(self) -> dict:
        return {
            "grounding": self.grounding.model_dump(),
            "coherence": self.coherence.model_dump(),
            "pedagogy": self.pedagogy.model_dump(),
            "summary": self.summary.model_dump(),
            "prompt_version_id": self.prompt_version_id,
        }


async def critique_content(
    content: dict | str,
    rag_context: str,
    *,
    audience: str = "",
    objectives: str = "",
    prompts: PromptSet,
) -> CritiqueResult:
    content_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
    common = dict(content=content_str, rag_context=rag_context, audience=audience, objectives=objectives)

    grounding, coherence, pedagogy = await asyncio.gather(
        chat_structured(prompts.system_prompt, prompts.render("grounding", **common), DimensionScore),
        chat_structured(prompts.system_prompt, prompts.render("coherence", **common), DimensionScore),
        chat_structured(prompts.system_prompt, prompts.render("pedagogy", **common), DimensionScore),
    )
    summary = await chat_structured(
        prompts.system_prompt,
        prompts.render(
            "summary",
            **common,
            grounding=grounding.feedback,
            coherence=coherence.feedback,
            pedagogy=pedagogy.feedback,
        ),
        CritiqueSummary,
    )
    return CritiqueResult(grounding, coherence, pedagogy, summary, prompts.version_id)


async def score_dimensions(
    content: dict | str,
    rag_context: str,
    *,
    audience: str = "",
    objectives: str = "",
    prompts: PromptSet,
    target: LLMTarget,
) -> tuple[dict[str, DimensionScore], dict[str, str]]:
    """Score the three dimensions without the workflow-oriented revise summary.

    The offline batch benchmark reports these dimensions and their findings. It
    deliberately does not turn the scores into a pass/revise action.
    """
    content_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
    common = dict(content=content_str, rag_context=rag_context, audience=audience, objectives=objectives)
    names = ("grounding", "coherence", "pedagogy")
    results = await asyncio.gather(
        *(chat_structured(prompts.system_prompt, prompts.render(name, **common), DimensionScore, target=target) for name in names),
        return_exceptions=True,
    )
    scores: dict[str, DimensionScore] = {}
    errors: dict[str, str] = {}
    for name, result in zip(names, results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, Exception):
            errors[name] = type(result).__name__
        elif isinstance(result, BaseException):
            raise result
        else:
            scores[name] = result
    return scores, errors


def critique_sync(db: Session, content: dict | str, rag_context: str, **kw) -> CritiqueResult:
    prompts = get_active(db, "critique")
    return asyncio.run(critique_content(content, rag_context, prompts=prompts, **kw))
