"""LMS review requests must reach the reviewer in exactly the prompt format each task was
trained and evaluated with, or the adapter's measured behaviour does not apply."""
from __future__ import annotations

import pytest

from evaltrain.prompts import DISTRACTORS, GROUNDING, RUBRIC, chat
from evaltrain.review_batch import render
from evaltrain.tasks.oak import RUBRIC_TEXT


def test_grounding_request_uses_the_training_template():
    ex = render({"id": "D1|slide|s1", "task": "ragtruth_grounding", "fields": {"context": "Source.", "response": "Slide."}, "ref": {"asset_id": "D1"}})
    assert ex.messages == chat(GROUNDING.format(context="Source.", response="Slide."))
    assert (ex.id, ex.task, ex.target, ex.meta) == ("D1|slide|s1", "ragtruth_grounding", None, {"ref": {"asset_id": "D1"}})


def test_distractor_request_matches_the_oak_rendering():
    ex = render({"id": "Q1|question|0", "task": "oak_distractors", "fields": {"question": " When? ", "answer": "Within 1 hour", "distractors": ["Within 2 hours ", "Within a day"]}})
    expected = DISTRACTORS.format(rubric=RUBRIC_TEXT, question="When?", answer="Within 1 hour", distractors="- Within 2 hours\n- Within a day")
    assert ex.messages == chat(expected)


def test_rubric_request_fills_every_field():
    fields = {"instruction": "I", "response": "R", "reference": "F", "criteria": "C", **{f"score{i}": f"S{i}" for i in range(1, 6)}}
    ex = render({"id": "D1|rubric|depth", "task": "prometheus_rubric", "fields": fields})
    assert ex.messages == chat(RUBRIC.format(**fields))


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        ({"id": "x", "task": "summarise", "fields": {}}, "unknown task"),
        ({"id": "x", "task": "ragtruth_grounding", "fields": {"context": "c"}}, "missing fields"),
        ({"id": "x", "task": "oak_distractors", "fields": {"question": "q", "answer": "a", "distractors": []}}, "missing fields"),
    ],
)
def test_malformed_requests_are_rejected(request_, message):
    with pytest.raises(ValueError, match=message):
        render(request_)
