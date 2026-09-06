"""Single entry point for every LLM call.

Everything talks to an OpenAI-compatible endpoint (vLLM, Ollama, llama.cpp),
so swapping models or servers is an env change, never a code change.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)


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
    resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=max_tokens or settings.llm_max_tokens,
    )
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
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_tokens=settings.llm_max_tokens,
            response_format={"type": "json_object"},
        )
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
