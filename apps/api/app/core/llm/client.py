"""Single entry point for every LLM call.

Everything talks to an OpenAI-compatible endpoint (vLLM, Ollama, llama.cpp),
so swapping models or servers is an env change, never a code change.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import math
from collections.abc import Coroutine
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from time import perf_counter
from typing import Any

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

# Rough characters-per-token for the mixed English/technical prose we send.
# Deliberately below the ~4.0 real-world ratio so the estimate errs high and the
# guard trips before the server does.
_CHARS_PER_TOKEN = 3.5
# Per-message chat-template overhead (role markers, separators).
_MESSAGE_OVERHEAD_TOKENS = 4

# Completed requests to the model server in this process. Generation jobs report
# the delta, since repair retries make the real count differ from the step count.
_call_count = 0
_async_clients: dict[LLMTarget, AsyncOpenAI] = {}


def llm_call_count() -> int:
    return _call_count


def _count_call() -> None:
    global _call_count
    _call_count += 1


@dataclass(frozen=True)
class LLMTarget:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    temperature: float
    max_tokens: int
    context_tokens: int
    timeout_seconds: int
    role: str


def generator_target() -> LLMTarget:
    return LLMTarget(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        context_tokens=settings.llm_context_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        role="generator",
    )


def judge_target() -> LLMTarget | None:
    """Return the explicitly configured benchmark judge; never fall back to the generator."""
    if not (settings.judge_base_url.strip() and settings.judge_api_key.strip() and settings.judge_model.strip()):
        return None
    return LLMTarget(
        base_url=settings.judge_base_url,
        api_key=settings.judge_api_key,
        model=settings.judge_model,
        temperature=settings.judge_temperature,
        max_tokens=settings.judge_max_tokens,
        context_tokens=settings.judge_context_tokens,
        timeout_seconds=settings.judge_timeout_seconds,
        role="judge",
    )


@dataclass
class LLMCallEvent:
    role: str
    model: str
    elapsed_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "model": self.model,
            "elapsed_ms": self.elapsed_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "error": self.error,
        }


@dataclass
class LLMCallTrace:
    events: list[LLMCallEvent] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        prompt = [event.prompt_tokens for event in self.events if event.prompt_tokens is not None]
        completion = [event.completion_tokens for event in self.events if event.completion_tokens is not None]
        return {
            "calls": len(self.events),
            "prompt_tokens": sum(prompt) if prompt and len(prompt) == len(self.events) else None,
            "completion_tokens": sum(completion) if completion and len(completion) == len(self.events) else None,
            "usage_reported_calls": sum(event.prompt_tokens is not None or event.completion_tokens is not None for event in self.events),
            "latency_ms": sum(event.elapsed_ms for event in self.events),
            "errors": sum(event.error is not None for event in self.events),
            "events": [event.as_dict() for event in self.events],
        }


_active_call_trace: contextvars.ContextVar[LLMCallTrace | None] = contextvars.ContextVar("llm_call_trace", default=None)


@contextmanager
def collect_llm_calls(trace: LLMCallTrace):
    token = _active_call_trace.set(trace)
    try:
        yield trace
    finally:
        _active_call_trace.reset(token)


def _record_call(target: LLMTarget, started: float, response: Any = None, error: Exception | None = None) -> None:
    trace = _active_call_trace.get()
    if trace is None:
        return
    usage = getattr(response, "usage", None) if response is not None else None
    trace.events.append(
        LLMCallEvent(
            role=target.role,
            model=target.model,
            elapsed_ms=round((perf_counter() - started) * 1000),
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            error=type(error).__name__ if error else None,
        )
    )


class ContextOverflowError(RuntimeError):
    """Prompt + reserved output would not fit the server's context window.

    Raised instead of letting the call through: Ollama and vLLM both drop the
    oldest tokens silently, which deletes retrieved evidence from the prompt and
    produces a confident, ungrounded answer that nothing downstream can detect.
    """


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def prompt_token_budget(max_tokens: int | None = None, *, context_tokens: int | None = None) -> int:
    """Tokens available for the prompt once space for the reply is reserved.

    Use this to decide how many retrieved chunks fit before building a prompt,
    rather than building one and catching ContextOverflowError.
    """
    context = settings.llm_context_tokens if context_tokens is None else context_tokens
    return context - (max_tokens or settings.llm_max_tokens)


def _guard_context(messages: list[dict], max_tokens: int, *, context_tokens: int | None = None) -> int:
    """Refuse a prompt the server would silently truncate. Returns the estimate."""
    estimate = sum(estimate_tokens(str(m.get("content") or "")) + _MESSAGE_OVERHEAD_TOKENS for m in messages)
    context = settings.llm_context_tokens if context_tokens is None else context_tokens
    budget = prompt_token_budget(max_tokens, context_tokens=context)
    if estimate > budget:
        raise ContextOverflowError(
            f"Prompt is ~{estimate} tokens but only {budget} fit "
            f"(context window={context} minus {max_tokens} reserved for the reply). "
            "Retrieve fewer chunks, lower the target max tokens, or raise the server's window "
            "(OLLAMA_CONTEXT_LENGTH / vLLM --max-model-len) and the matching target context setting together."
        )
    return estimate


def _warn_if_truncated(resp, estimate: int, *, context_tokens: int | None = None) -> None:
    """Second line of defence: the server reported far fewer prompt tokens than we sent."""
    usage = getattr(resp, "usage", None)
    reported = getattr(usage, "prompt_tokens", None) if usage else None
    if not reported:
        return
    context = settings.llm_context_tokens if context_tokens is None else context_tokens
    if reported >= context:
        log.error(
            "server reports prompt_tokens=%s at or above the configured window (%s); "
            "evidence was almost certainly dropped. Check that the server's context length "
            "matches the selected target context setting.",
            reported, context,
        )
    elif reported < estimate * 0.65:
        log.warning(
            "server reports prompt_tokens=%s but ~%s were sent; the server's context window "
            "is probably smaller than the selected target context setting (%s) and truncated the prompt.",
            reported, estimate, context,
        )


def get_async_client(target: LLMTarget | None = None) -> AsyncOpenAI:
    selected = target or generator_target()
    client = _async_clients.get(selected)
    if client is None:
        client = AsyncOpenAI(base_url=selected.base_url, api_key=selected.api_key, timeout=selected.timeout_seconds)
        _async_clients[selected] = client
    return client


async def _close_async_clients() -> None:
    clients = list(_async_clients.values())
    _async_clients.clear()
    for client in clients:
        await client.close()


def run_blocking[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async LLM workflow from synchronous code (the worker's job handlers).

    `asyncio.run` creates a new event loop per call, but the cached AsyncOpenAI
    client pools connections bound to the loop that opened them; reusing it in
    the next job fails with "Event loop is closed". Start and end each run with
    a fresh client.
    """

    async def _main() -> T:
        try:
            return await coro
        finally:
            await _close_async_clients()

    # Async clients are bound to the loop that created them; do not reuse them
    # across the fresh event loops created by successive worker jobs.
    _async_clients.clear()
    return asyncio.run(_main())


@lru_cache
def get_sync_client(target: LLMTarget | None = None) -> OpenAI:
    selected = target or generator_target()
    return OpenAI(base_url=selected.base_url, api_key=selected.api_key, timeout=selected.timeout_seconds)


def get_pydantic_ai_model():
    """pydantic-ai model bound to the same local endpoint (for agent-style generation)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(settings.llm_model, provider=OpenAIProvider(base_url=settings.llm_base_url, api_key=settings.llm_api_key))


async def chat_text(
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    target: LLMTarget | None = None,
) -> str:
    selected = target or generator_target()
    client = get_async_client(selected)
    reply_tokens = max_tokens or selected.max_tokens
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    estimate = _guard_context(messages, reply_tokens, context_tokens=selected.context_tokens)
    started = perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=selected.model,
            messages=messages,
            temperature=selected.temperature if temperature is None else temperature,
            max_tokens=reply_tokens,
        )
    except Exception as exc:
        _record_call(selected, started, error=exc)
        raise
    _count_call()
    _record_call(selected, started, response=resp)
    _warn_if_truncated(resp, estimate, context_tokens=selected.context_tokens)
    return resp.choices[0].message.content or ""


async def chat_structured[T: BaseModel](
    system: str,
    user: str,
    schema: type[T],
    *,
    temperature: float | None = None,
    retries: int = 2,
    target: LLMTarget | None = None,
) -> T:
    """Ask for JSON matching `schema`; validate; retry with the validation error fed back.

    Uses `response_format=json_object` (supported by vLLM and Ollama). vLLM users
    can tighten this to guided JSON schema decoding via `extra_body` later.
    """
    selected = target or generator_target()
    client = get_async_client(selected)
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    sys_prompt = f"{system}\n\nRespond ONLY with a JSON object matching this schema:\n{schema_json}"
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        # Re-checked every attempt: each repair round appends the bad output and
        # the validation error, so a prompt that fitted initially can outgrow the
        # window partway through the loop.
        estimate = _guard_context(messages, selected.max_tokens, context_tokens=selected.context_tokens)
        started = perf_counter()
        try:
            resp = await client.chat.completions.create(
                model=selected.model,
                messages=messages,
                temperature=selected.temperature if temperature is None else temperature,
                max_tokens=selected.max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            _record_call(selected, started, error=exc)
            raise
        _count_call()
        _record_call(selected, started, response=resp)
        _warn_if_truncated(resp, estimate, context_tokens=selected.context_tokens)
        raw = resp.choices[0].message.content or ""
        try:
            return schema.model_validate_json(_strip_fences(raw))
        except (ValidationError, ValueError) as exc:
            last_err = exc
            log.warning("structured output invalid (attempt %s/%s): %s", attempt + 1, retries + 1, exc)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"That was not valid. Error:\n{exc}\nReturn corrected JSON only."})
    raise RuntimeError(f"LLM failed to produce valid {schema.__name__}: {last_err}")


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()
