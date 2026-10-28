"""The reviewer adapter only behaves as evaluated when it receives the same request it
was trained and scored with: its own served name, greedy decoding, thinking off, and
inputs that fit without truncation. These tests pin that request shape."""
import asyncio
from types import SimpleNamespace

import pytest

from app.config import settings
from app.core.llm import reviewer
from app.core.llm.client import ContextOverflowError

MESSAGES = [{"role": "system", "content": "You are a careful reviewer."}, {"role": "user", "content": "Check this."}]


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, **kwargs):
        self.init = kwargs
        self.calls: list[dict] = []
        self.closed = False
        _FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        digit = SimpleNamespace(token="4", logprob=-0.1, top_logprobs=[SimpleNamespace(token="4", logprob=-0.1), SimpleNamespace(token="3", logprob=-2.5)])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"score": 4}'), finish_reason="stop", logprobs=SimpleNamespace(content=[digit]))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=7),
        )


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "reviewer_enabled", True)
    _FakeClient.instances.clear()
    monkeypatch.setattr(reviewer, "AsyncOpenAI", _FakeClient)


def test_reviewer_is_off_by_default():
    assert settings.reviewer_enabled is False
    with pytest.raises(reviewer.ReviewerDisabledError):
        asyncio.run(reviewer.review(MESSAGES))


def test_oversized_review_is_refused_before_any_request(enabled):
    huge = [{"role": "user", "content": "word " * (settings.reviewer_context_tokens * 2)}]
    with pytest.raises(ContextOverflowError) as exc:
        asyncio.run(reviewer.review(huge))
    assert "scoped cases" in str(exc.value)
    assert _FakeClient.instances == []  # no connection was opened


def test_request_matches_how_the_adapter_was_evaluated(enabled):
    before = reviewer.reviewer_call_count()
    reply = asyncio.run(reviewer.review(MESSAGES, logprobs=True))

    (client,) = _FakeClient.instances
    assert client.init["base_url"] == settings.reviewer_base_url
    assert client.closed
    (call,) = client.calls
    assert call["model"] == settings.reviewer_model
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == settings.reviewer_max_tokens
    assert call["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert call["top_logprobs"] == reviewer.TOP_LOGPROBS

    assert reply.text == '{"score": 4}'
    assert (reply.prompt_tokens, reply.completion_tokens) == (120, 7)
    assert reply.top_logprobs == [[("4", -0.1), ("3", -2.5)]]
    assert reviewer.reviewer_call_count() == before + 1


def test_logprobs_are_only_requested_when_asked(enabled):
    reply = asyncio.run(reviewer.review(MESSAGES))
    (call,) = _FakeClient.instances[0].calls
    assert "logprobs" not in call and "top_logprobs" not in call
    assert reply.top_logprobs is None
