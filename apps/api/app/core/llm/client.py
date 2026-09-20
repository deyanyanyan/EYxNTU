"""Single entry point for every LLM call.

Everything talks to an OpenAI-compatible endpoint (vLLM, Ollama, llama.cpp),
so swapping models or servers is an env change, never a code change.
"""
from __future__ import annotations

import json
import logging
import math
from functools import lru_cache

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


class ContextOverflowError(RuntimeError):
    """Prompt + reserved output would not fit the server's context window.

    Raised instead of letting the call through: Ollama and vLLM both drop the
    oldest tokens silently, which deletes retrieved evidence from the prompt and
    produces a confident, ungrounded answer that nothing downstream can detect.
    """


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def prompt_token_budget(max_tokens: int | None = None) -> int:
    """Tokens available for the prompt once space for the reply is reserved.

    Use this to decide how many retrieved chunks fit before building a prompt,
    rather than building one and catching ContextOverflowError.
    """
    return settings.llm_context_tokens - (max_tokens or settings.llm_max_tokens)


def _guard_context(messages: list[dict], max_tokens: int) -> int:
    """Refuse a prompt the server would silently truncate. Returns the estimate."""
    estimate = sum(estimate_tokens(str(m.get("content") or "")) + _MESSAGE_OVERHEAD_TOKENS for m in messages)
    budget = prompt_token_budget(max_tokens)
    if estimate > budget:
        raise ContextOverflowError(
            f"Prompt is ~{estimate} tokens but only {budget} fit "
            f"(LLM_CONTEXT_TOKENS={settings.llm_context_tokens} minus {max_tokens} reserved for the reply). "
            "Retrieve fewer chunks, lower LLM_MAX_TOKENS, or raise the server's window "
            "(OLLAMA_CONTEXT_LENGTH / vLLM --max-model-len) and LLM_CONTEXT_TOKENS together."
        )
    return estimate


def _warn_if_truncated(resp, estimate: int) -> None:
    """Second line of defence: the server reported far fewer prompt tokens than we sent."""
    usage = getattr(resp, "usage", None)
    reported = getattr(usage, "prompt_tokens", None) if usage else None
    if not reported:
        return
    if reported >= settings.llm_context_tokens:
        log.error(
            "server reports prompt_tokens=%s at or above the configured window (%s); "
            "evidence was almost certainly dropped. Check that the server's context length "
            "matches LLM_CONTEXT_TOKENS.",
            reported, settings.llm_context_tokens,
        )
    elif reported < estimate * 0.65:
        log.warning(
            "server reports prompt_tokens=%s but ~%s were sent; the server's context window "
            "is probably smaller than LLM_CONTEXT_TOKENS=%s and truncated the prompt.",
            reported, estimate, settings.llm_context_tokens,
        )


@lru_cache
def get_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=settings.llm_timeout_seconds)


@lru_cache
def get_sync_client() -> OpenAI:
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=settings.llm_timeout_seconds)


def get_pydantic_ai_model():
    """pydantic-ai model bound to the same local endpoint (for agent-style generation)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(settings.llm_model, provider=OpenAIProvider(base_url=settings.llm_base_url, api_key=settings.llm_api_key))


async def chat_text(system: str, user: str, *, temperature: float | None = None, max_tokens: int | None = None) -> str:
    client = get_async_client()
    reply_tokens = max_tokens or settings.llm_max_tokens
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    estimate = _guard_context(messages, reply_tokens)
    resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=reply_tokens,
    )
    _warn_if_truncated(resp, estimate)
    return resp.choices[0].message.content or ""


async def chat_structured[T: BaseModel](system: str, user: str, schema: type[T], *, temperature: float | None = None, retries: int = 2) -> T:
    """Ask for JSON matching `schema`; validate; retry with the validation error fed back.

    Uses `response_format=json_object` (supported by vLLM and Ollama). vLLM users
    can tighten this to guided JSON schema decoding via `extra_body` later.
    """
    client = get_async_client()
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    sys_prompt = f"{system}\n\nRespond ONLY with a JSON object matching this schema:\n{schema_json}"
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        # Re-checked every attempt: each repair round appends the bad output and
        # the validation error, so a prompt that fitted initially can outgrow the
        # window partway through the loop.
        estimate = _guard_context(messages, settings.llm_max_tokens)
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_tokens=settings.llm_max_tokens,
            response_format={"type": "json_object"},
        )
        _warn_if_truncated(resp, estimate)
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
