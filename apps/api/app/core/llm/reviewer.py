"""Client for the custom reviewer model (the LoRA adapter trained in packages/eval/training).

Kept apart from the generation client: its own endpoint, served model name and context
budget, greedy decoding and the chat template's thinking mode off, because that is how
the adapter was trained and evaluated (its serving.json records the same settings).
Requests must be rendered with the training templates in
packages/eval/training/evaltrain/prompts.py; other prompt formats lose what the
adapter learned.

Nothing in the generation pipeline calls this yet. REVIEWER_ENABLED stays false until a
validated adapter is deployed and `make served-check` passes against it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import settings
from app.core.llm.client import ContextOverflowError, estimate_tokens

log = logging.getLogger(__name__)

TOP_LOGPROBS = 20  # enough to cover every score digit 1-5 at the score position
_MESSAGE_OVERHEAD_TOKENS = 4

_call_count = 0


def reviewer_call_count() -> int:
    return _call_count


class ReviewerDisabledError(RuntimeError):
    """REVIEWER_ENABLED is false: no validated reviewer is deployed."""


@dataclass
class ReviewerReply:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    # Per generated token: (candidate text, log-probability) pairs; None unless requested.
    top_logprobs: list[list[tuple[str, float]]] | None = None


def _guard_context(messages: list[dict], max_tokens: int) -> int:
    estimate = sum(estimate_tokens(str(m.get("content") or "")) + _MESSAGE_OVERHEAD_TOKENS for m in messages)
    budget = settings.reviewer_context_tokens - max_tokens
    if estimate > budget:
        raise ContextOverflowError(
            f"Review prompt is ~{estimate} tokens but only {budget} fit "
            f"(REVIEWER_CONTEXT_TOKENS={settings.reviewer_context_tokens} minus {max_tokens} reserved for the reply). "
            "Split the review into scoped cases (fewer requirements or passages per request); "
            "never drop evidence to make it fit."
        )
    return estimate


async def review(messages: list[dict], *, max_tokens: int | None = None, logprobs: bool = False) -> ReviewerReply:
    """One review request in the adapter's training format; returns the raw reply.

    Parsing and validation belong to the caller, which knows the task's JSON shape.
    """
    if not settings.reviewer_enabled:
        raise ReviewerDisabledError("REVIEWER_ENABLED is false: deploy and validate a reviewer adapter first")
    reply_tokens = max_tokens or settings.reviewer_max_tokens
    _guard_context(messages, reply_tokens)
    request = {
        "model": settings.reviewer_model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": reply_tokens,
        # vLLM extension: the template's thinking mode, off for this adapter
        "extra_body": {"chat_template_kwargs": {"enable_thinking": settings.reviewer_enable_thinking}},
    }
    if logprobs:
        request |= {"logprobs": True, "top_logprobs": TOP_LOGPROBS}
    # A client per call: the worker runs each job in a fresh event loop, and a cached
    # client's connection pool stays bound to the loop that created it.
    async with AsyncOpenAI(base_url=settings.reviewer_base_url, api_key=settings.reviewer_api_key, timeout=settings.reviewer_timeout_seconds) as client:
        resp = await client.chat.completions.create(**request)
    global _call_count
    _call_count += 1

    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    top = None
    content = getattr(getattr(choice, "logprobs", None), "content", None)
    if logprobs and content:
        top = [[(t.token, t.logprob) for t in (tok.top_logprobs or [])] for tok in content]
    if getattr(choice, "finish_reason", None) == "length":
        log.warning("reviewer reply hit max_tokens=%s; the JSON is probably incomplete", reply_tokens)
    return ReviewerReply(
        text=choice.message.content or "",
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        top_logprobs=top,
    )
