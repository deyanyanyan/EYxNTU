"""Course revisions without a database or model: blocks, citations and reviewer findings
across versions, the instructions a fix sends, outline comparison, and single-slide and
single-question rewrites against the deck's own numbered references."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.generation import brief, outline, revise, revision
from app.core.generation.quiz.service import RawQuestion

DECK = {
    "slides": [
        {"id": "s1", "layout": "bullets", "title": "Creating strong passwords", "bullets": ["At least 12 characters long [1]", "Never reuse a password [1]"], "table": None, "notes": ""},
        {"id": "s2", "layout": "bullets", "title": "Reporting", "bullets": ["Report within 1 hour [2]"], "table": None, "notes": "Be quick [2]"},
    ],
    "references": {"1": {"chunk_id": "c1"}, "2": {"chunk_id": "c2"}},
}
REVIEW = {"reviewer": {
    "adapter": "main-27b-v1",
    "slides": {"s1": {"valid": True, "issues": [{"span": "12 characters", "type": "evident_conflict"}]}, "s2": {"valid": True, "issues": []}},
    "rubric": [{"criterion": "Instructional depth", "valid": True, "score": 2, "feedback": "Misses the 1-hour rule."}],
    "questions": {"0": {"valid": True, "score": 1}, "1": {"valid": True, "score": 4}},
}}


def test_replace_block_keeps_the_slide_id_and_detects_the_change():
    after = revision.replace_block("slides", DECK, "s1", {"id": "s9", "title": "Strong passwords", "bullets": ["At least 14 characters long [1]"]})
    assert after["slides"][0]["id"] == "s1" and after["slides"][0]["bullets"] == ["At least 14 characters long [1]"]
    assert revision.changed_blocks("slides", DECK, after) == {"s1"}
    assert DECK["slides"][0]["bullets"][0].startswith("At least 12")  # the original is untouched
    with pytest.raises(revision.RevisionError):
        revision.replace_block("slides", DECK, "s7", {})


def test_citations_follow_markers_through_the_references():
    assert revision.slide_links(DECK["slides"], DECK["references"]) == [("s1", "c1"), ("s2", "c2")]
    stats = revision.deck_stats([{**DECK["slides"][0], "bullets": ["No marker", "Bad marker [7]"]}], DECK["references"])
    assert stats["bullets_without_citation"] == 1 and stats["invalid_citation_numbers"] == [7]
    quiz = {"questions": [{"stem": "When?", "chunk_id": "c2", "source_span": "within 1 hour"}, {"stem": "No source"}]}
    cites = revision.citations_for("quiz", quiz)
    assert [(c.block_id, c.chunk_id, c.quote) for c in cites] == [("q1", "c2", "within 1 hour")]


def test_findings_on_changed_blocks_do_not_carry_over():
    carried = revision.carry_review(REVIEW, "slides", {"s1"})
    review = carried["reviewer"]
    assert "s1" not in review["slides"] and "s2" in review["slides"]
    assert review["changed"] == ["s1"] and review["rubric_stale"] is True
    assert "s1" in REVIEW["reviewer"]["slides"]  # the earlier version keeps its findings
    assert revision.carry_review(REVIEW, "slides", set()) == REVIEW


def test_a_fix_turns_findings_into_instructions():
    assert brief.slide_findings(REVIEW, "s1") == ['"12 characters" contradicts the references. Correct it to match them.']
    assert brief.question_findings(REVIEW, "0") and not brief.question_findings(REVIEW, "1")
    text = brief.compose("Lead with the rule.", ["examples", "fix"], brief.slide_findings(REVIEW, "s1"))
    assert text.startswith("Lead with the rule.") and "workplace example" in text and '"12 characters" contradicts' in text
    assert brief.compose(None, []) == "" and brief.appendix("") == ""
    deck, quiz = SimpleNamespace(critique=REVIEW), SimpleNamespace(critique=REVIEW)
    lesson = brief.lesson_findings(deck, quiz)
    assert lesson[0].startswith("Slide 1:") and any(f.startswith("Question 1:") for f in lesson) and any("Instructional depth (2/5)" in f for f in lesson)
    assert [(a is deck, b) for a, b in brief.flagged_blocks(deck, quiz)] == [(True, "s1"), (False, "0")]


def _plan(title: str, lessons: list[tuple[str, str, str | None]]):
    """lessons: (id, title, origin_id) in one module."""
    module = SimpleNamespace(position=1, title="Module", lessons=[SimpleNamespace(id=i, title=t, origin_id=o, position=n) for n, (i, t, o) in enumerate(lessons, 1)])
    return SimpleNamespace(title=title, modules=[module])


def test_outline_versions_compare_by_lesson_lineage():
    v1 = _plan("Security", [("a", "Passwords", None), ("b", "Reporting", None), ("c", "Phishing", None)])
    v2 = _plan("Security basics", [("b2", "Reporting incidents", "b"), ("a2", "Passwords", "a"), ("d", "Travel", None)])
    changes = {(c["kind"], c["detail"]) for c in outline.compare(v1, v2)}
    assert ("renamed", "“Security” → “Security basics”") in changes
    assert ("renamed", "“Reporting” → “Reporting incidents”") in changes
    assert ("moved", "“Passwords” from 1.1 to 1.2") in changes
    assert ("added", "“Travel” in Module") in changes and ("removed", "“Phishing” from Module") in changes


class _FakeDB:
    def __init__(self, objects):
        self.objects = objects

    def get(self, model, key):
        return self.objects.get((model.__name__, key))


@pytest.fixture
def lesson_db(monkeypatch):
    plan = SimpleNamespace(id="p1", project_id="pr1", learning_objectives=[{"id": "o1", "text": "Report incidents on time"}])
    db = _FakeDB({
        ("Lesson", "l1"): SimpleNamespace(id="l1", title="Reporting incidents", module_id="m1", objective_ids=["o1"]),
        ("Module", "m1"): SimpleNamespace(id="m1", plan_id="p1"),
        ("CoursePlan", "p1"): plan,
        ("Project", "pr1"): SimpleNamespace(id="pr1", target_audience="new staff"),
    })
    passages = [SimpleNamespace(chunk_id="c2", source_name="handbook.md", heading_path="5 Reporting", text="Report within 1 hour of noticing it.")]
    monkeypatch.setattr(revise, "chunks_by_id", lambda _db, ids: [c for c in passages if c.chunk_id in ids])
    return db


def test_slide_rewrite_keeps_reference_numbers_and_the_slide_id(lesson_db, monkeypatch):
    seen = {}

    async def fake_chat(system, user, schema, temperature=None):
        seen["user"] = user
        return schema(id="whatever", layout="bullets", title="How and when to report", bullets=["Report within 1 hour [2]"], notes="")

    monkeypatch.setattr(revise, "chat_structured", fake_chat)
    prompts = SimpleNamespace(system_prompt="", render=lambda name, **v: json.dumps({"template": name, **v}))
    deck = SimpleNamespace(lesson_id="l1", content=DECK)
    out = asyncio.run(revise.rewrite_slide(lesson_db, deck, "s2", "Fix the deadline.", prompts))
    sent = json.loads(seen["user"])
    assert out["id"] == "s2" and out["bullets"] == ["Report within 1 hour [2]"]
    assert sent["template"] == "slide" and sent["instructions"] == "Fix the deadline."
    # chunk c1 is gone (its source was deleted): [2] keeps its number rather than becoming [1]
    assert sent["rag_context"].startswith("[2] handbook.md › 5 Reporting") and "[1]" not in sent["rag_context"]
    assert "Creating strong passwords" in sent["other_slides"] and "Reporting:" not in sent["other_slides"]


def test_question_rewrite_can_change_only_the_wrong_options(lesson_db, monkeypatch):
    async def fake_chat(system, user, schema, temperature=None):
        return RawQuestion(stem="Something else?", correct_answer="Changed", distractors=["Within 2 hours", "Within 4 hours", "Within 8 hours"],
                           explanation="x", source_span="different span", reference=9, difficulty="easy")

    monkeypatch.setattr(revise, "chat_structured", fake_chat)
    prompts = SimpleNamespace(system_prompt="", render=lambda name, **v: name)
    quiz = SimpleNamespace(lesson_id="l1", content={
        "questions": [{"stem": "Within what time must you report an incident?", "options": ["1 character", "Within 1 hour"], "answer_index": 1,
                       "explanation": "The handbook says so [2]", "difficulty": "easy", "source_span": "Report within 1 hour of noticing it.", "chunk_id": "c2"}],
        "references": {"2": {"chunk_id": "c2"}},
    })
    q = asyncio.run(revise.rewrite_question(lesson_db, quiz, "0", "Better options.", prompts, options_only=True))
    assert q["stem"].startswith("Within what time") and q["options"][q["answer_index"]] == "Within 1 hour"
    assert set(q["options"]) == {"Within 1 hour", "Within 2 hours", "Within 4 hours", "Within 8 hours"} and q["chunk_id"] == "c2"
