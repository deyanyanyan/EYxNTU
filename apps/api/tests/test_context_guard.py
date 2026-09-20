"""The context guard exists because both Ollama and vLLM truncate oversized
prompts without raising, which deletes retrieved evidence from the prompt and
leaves a confident, ungrounded answer that nothing downstream can detect."""
import asyncio
import logging

import pytest

from app.config import settings
from app.core.llm.client import (
    ContextOverflowError,
    _guard_context,
    _warn_if_truncated,
    chat_text,
    estimate_tokens,
    prompt_token_budget,
)


def _messages(chars: int) -> list[dict]:
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": "x" * chars}]


def test_budget_reserves_room_for_the_reply():
    assert prompt_token_budget(1000) == settings.llm_context_tokens - 1000
    assert prompt_token_budget() == settings.llm_context_tokens - settings.llm_max_tokens


def test_estimate_errs_high_so_the_guard_trips_before_the_server():
    # Real English is ~4 chars/token; estimating low would let a truncating
    # prompt through, which is the failure this whole module prevents.
    assert estimate_tokens("a" * 4000) > 1000


def test_prompt_within_budget_passes():
    budget = prompt_token_budget(512)
    assert _guard_context(_messages(int(budget * 2)), 512) <= budget


def test_oversized_prompt_raises_instead_of_being_truncated():
    over = int(prompt_token_budget(512) * 3.5) + 5000
    with pytest.raises(ContextOverflowError) as exc:
        _guard_context(_messages(over), 512)
    # The message has to tell a teammate what to change, not just that it failed.
    assert "OLLAMA_CONTEXT_LENGTH" in str(exc.value)


def test_reply_reservation_counts_against_the_window():
    """A prompt that fits with a small reply must fail with a large one."""
    chars = int(prompt_token_budget(settings.llm_context_tokens // 2) * 3.0)
    _guard_context(_messages(chars), settings.llm_context_tokens // 2)
    with pytest.raises(ContextOverflowError):
        _guard_context(_messages(chars), settings.llm_context_tokens - 100)


def test_chat_text_refuses_before_calling_the_server():
    """No client is constructed, so this also proves the guard runs first."""
    huge = "word " * (settings.llm_context_tokens * 2)
    with pytest.raises(ContextOverflowError):
        asyncio.run(chat_text("sys", huge))


class _Usage:
    def __init__(self, prompt_tokens):
        self.prompt_tokens = prompt_tokens


class _Resp:
    def __init__(self, prompt_tokens):
        self.usage = _Usage(prompt_tokens)


def test_truncation_is_reported_when_the_server_saw_less_than_we_sent(caplog):
    with caplog.at_level(logging.WARNING):
        _warn_if_truncated(_Resp(prompt_tokens=4000), estimate=12000)
    assert "truncated" in caplog.text


def test_prompt_at_the_window_is_reported_as_an_error(caplog):
    with caplog.at_level(logging.ERROR):
        _warn_if_truncated(_Resp(prompt_tokens=settings.llm_context_tokens), estimate=settings.llm_context_tokens)
    assert "dropped" in caplog.text


def test_matching_usage_is_quiet(caplog):
    with caplog.at_level(logging.WARNING):
        _warn_if_truncated(_Resp(prompt_tokens=950), estimate=1000)
    assert caplog.text == ""
