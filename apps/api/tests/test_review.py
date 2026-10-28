"""Batch review round trip: the export must send the reviewer the formats it was trained
on, and the import must attach every finding to the slide or question it is about, keep
the reviewer's identity, and mark findings stale when the asset changed after export."""
import json
from types import SimpleNamespace

import pytest

from app.core.review.criteria import CRITERIA, CRITERIA_VERSION
from app.core.review.export import lesson_requests, slide_text, strip_markers
from app.core.review.importer import build_reviews, expected_score, import_results, reviewer_identity

DECK = {
    "slides": [
        {"id": "s1", "layout": "bullets", "title": "Reporting [1]", "bullets": ["Report within 24 hours [1]", "Call 4400 [2]"], "table": None, "notes": "Be quick [1]"},
        {"id": "s2", "layout": "table", "title": "Channels", "bullets": [], "table": [["When", "How"], ["Office hours", "Portal [1]"]], "notes": ""},
    ],
}
QUIZ = {"questions": [
    {"stem": "When?", "options": ["Later", "Within 1 hour", "Never"], "answer_index": 1},
    {"stem": "Broken", "options": ["A"], "answer_index": 3},  # no valid answer: not reviewed
]}
PASSAGES = [("1", "Report within 1 hour."), ("2", "Out of hours, call extension 4400.")]


def _requests():
    return lesson_requests(
        lesson_id="L1", lesson_title="Reporting incidents", audience="new staff", objectives=["Report incidents on time"],
        deck_id="D1", deck=DECK, quiz_id="Q1", quiz=QUIZ, passages=PASSAGES,
    )


def test_reviewed_text_has_no_citation_markers():
    assert strip_markers("Report within 24 hours [1] [12]") == "Report within 24 hours"
    text = slide_text(DECK["slides"][0])
    assert text == "Reporting\n- Report within 24 hours\n- Call 4400\nSpeaker notes: Be quick"
    assert slide_text(DECK["slides"][1]) == "Channels\nWhen | How\nOffice hours | Portal"


def test_requests_cover_every_slide_criterion_and_answerable_question():
    reqs = _requests()
    kinds = [r["ref"]["kind"] for r in reqs]
    assert kinds == ["slide", "slide"] + ["rubric"] * len(CRITERIA) + ["question"]
    assert len({r["id"] for r in reqs}) == len(reqs)

    slide = reqs[0]
    assert slide["task"] == "ragtruth_grounding"
    assert slide["ref"] == {"asset_id": "D1", "lesson_id": "L1", "kind": "slide", "block": "s1"}
    assert "[1] Report within 1 hour." in slide["fields"]["context"] and "[2] Out of hours" in slide["fields"]["context"]

    rubric = reqs[2]
    assert rubric["task"] == "prometheus_rubric" and rubric["ref"]["criterion"] == CRITERIA[0]["name"]
    assert set(rubric["fields"]) == {"instruction", "response", "reference", "criteria", "score1", "score2", "score3", "score4", "score5"}
    assert "Report incidents on time" in rubric["fields"]["instruction"] and rubric["fields"]["response"].startswith("Slide 1: Reporting")

    question = reqs[-1]
    assert question["task"] == "oak_distractors"
    assert question["fields"] == {"question": "When?", "answer": "Within 1 hour", "distractors": ["Later", "Never"]}
    assert question["ref"]["block"] == "0"


def test_no_grounding_or_rubric_requests_without_source_passages():
    reqs = lesson_requests(lesson_id="L1", lesson_title="T", audience="a", objectives=[], deck_id="D1", deck=DECK, quiz_id=None, quiz=None, passages=[])
    assert reqs == []


def test_expected_score_from_distribution():
    assert expected_score({"1": 0.5, "2": 0.5}) == 1.5
    assert expected_score({"4": 0.6, "5": 0.2}) == pytest.approx(4.25)  # renormalised over the digits seen
    assert expected_score(None) is None and expected_score({}) is None


def _rows():
    return [
        {"id": "D1|slide|s1", "valid": True, "parsed": {"issues": [{"span": "within 24 hours", "type": "evident_conflict", "implicit_true": False}]},
         "ref": {"asset_id": "D1", "kind": "slide", "block": "s1"}},
        {"id": "D1|slide|s2", "valid": False, "parsed": None, "error": "no JSON object found", "ref": {"asset_id": "D1", "kind": "slide", "block": "s2"}},
        {"id": "D1|rubric|instructional_depth", "valid": True, "parsed": {"score": 2, "feedback": "Wrong deadline."},
         "score_dist": {"score": {"2": 0.75, "3": 0.25}}, "ref": {"asset_id": "D1", "kind": "rubric", "block": "instructional_depth", "criterion": "Instructional depth"}},
        {"id": "Q1|question|0", "valid": True, "parsed": {"score": 4}, "score_dist": {"score": {"4": 1.0}}, "ref": {"asset_id": "Q1", "kind": "question", "block": "0"}},
        {"id": "orphan", "valid": True, "parsed": {"score": 3}, "ref": {}},  # no ref: ignored
    ]


def test_build_reviews_attaches_findings_to_blocks():
    reviews = build_reviews(_rows(), {"adapter": "main-27b-v1"})
    assert set(reviews) == {"D1", "Q1"}
    deck = reviews["D1"]
    assert deck["adapter"] == "main-27b-v1"
    assert deck["slides"]["s1"] == {"valid": True, "error": None, "issues": [{"span": "within 24 hours", "type": "evident_conflict", "implicit_true": False}]}
    assert deck["slides"]["s2"] == {"valid": False, "error": "no JSON object found", "issues": []}
    assert deck["rubric"] == [{"criterion_id": "instructional_depth", "criterion": "Instructional depth", "valid": True, "score": 2, "expected": 2.25, "feedback": "Wrong deadline."}]
    assert reviews["Q1"]["questions"] == {"0": {"valid": True, "score": 4, "expected": 4.0}}


def test_reviewer_identity_is_advisory_and_versioned():
    meta = {"reviewer": {"base_model": "Qwen/Qwen3.8-27B", "base_revision": "abc", "adapter": "main-27b-v1", "adapter_checkpoint": "checkpoint-1044", "prompt_version": "p1"},
            "finished_at": "2026-10-28T10:08:49+0800"}
    who = reviewer_identity(meta)
    assert who["advisory"] is True and who["criteria_version"] == CRITERIA_VERSION
    assert (who["base_model"], who["adapter"], who["reviewed_at"]) == ("Qwen/Qwen3.8-27B", "main-27b-v1", "2026-10-28T10:08:49+0800")


class _FakeDB:
    def __init__(self, assets):
        self.assets = assets
        self.committed = False

    def get(self, _model, asset_id):
        return self.assets.get(asset_id)

    def commit(self):
        self.committed = True


def test_import_marks_stale_assets_and_keeps_other_critique(tmp_path):
    results = tmp_path / "results.jsonl"
    results.write_text("".join(json.dumps(r) + "\n" for r in _rows()), encoding="utf-8")
    (tmp_path / "results.jsonl.meta.json").write_text(json.dumps({"reviewer": {"adapter": "main-27b-v1"}, "finished_at": "t"}), encoding="utf-8")
    manifest = tmp_path / "requests.jsonl.manifest.json"
    manifest.write_text(json.dumps({"assets": {"D1": 1, "Q1": 1}}), encoding="utf-8")
    deck = SimpleNamespace(project_id="P1", version=2, critique={"other": {"kept": True}})  # edited after export
    quiz = SimpleNamespace(project_id="P1", version=1, critique=None)
    db = _FakeDB({"D1": deck, "Q1": quiz})

    summary = import_results(db, "P1", results, manifest=manifest)

    assert db.committed
    assert summary == {"assets": 2, "skipped_assets": [], "slides": 2, "issues": 1, "rubric": 1, "questions": 1, "invalid": 1, "stale": 1}
    assert deck.critique["other"] == {"kept": True}
    assert deck.critique["reviewer"]["stale"] is True and deck.critique["reviewer"]["asset_version"] == 1
    assert quiz.critique["reviewer"]["stale"] is False and quiz.critique["reviewer"]["adapter"] == "main-27b-v1"


def test_import_skips_assets_of_other_projects(tmp_path):
    results = tmp_path / "results.jsonl"
    results.write_text("".join(json.dumps(r) + "\n" for r in _rows()), encoding="utf-8")
    other = SimpleNamespace(project_id="P2", version=1, critique=None)
    db = _FakeDB({"D1": other})

    summary = import_results(db, "P1", results)

    assert summary["assets"] == 0 and sorted(summary["skipped_assets"]) == ["D1", "Q1"]
    assert other.critique is None
