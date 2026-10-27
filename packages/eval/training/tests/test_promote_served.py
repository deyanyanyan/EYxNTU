from __future__ import annotations

import json

import pytest

from evaltrain import promote, served_check
from evaltrain.callbacks import TRAINING_DONE_MARKER
from evaltrain.prompts import chat
from evaltrain.records import Example, write_jsonl


def _examples(n: int = 20) -> list[Example]:
    return [
        Example(id=f"oak:{i}", task="oak_distractors", dataset="oak", split="dev", group=f"oak:g{i}", messages=chat(f"question {i}"),
                target=None, gold={"score": 1 + i % 5, "subset": "dev"})
        for i in range(n)
    ]


def _predictions(examples, valid: bool = True) -> list[dict]:
    rows = []
    for e in examples:
        score = e.gold["score"]
        rows.append({"id": e.id, "task": e.task, "raw": json.dumps({"score": score}) if valid else "I think 3",
                     "parsed": {"score": score} if valid else None, "valid": valid, "strict": valid, "score_dist": {}})
    return rows


def test_served_check_passes_identical_replies_and_fails_degraded_ones(tmp_path):
    exs = _examples()
    write_jsonl(tmp_path / "examples.jsonl", exs)
    write_jsonl(tmp_path / "reference.jsonl", _predictions(exs))
    write_jsonl(tmp_path / "same.jsonl", _predictions(exs))
    write_jsonl(tmp_path / "broken.jsonl", _predictions(exs, valid=False))

    ok = served_check.compare(tmp_path / "examples.jsonl", tmp_path / "reference.jsonl", tmp_path / "same.jsonl")
    assert ok["passed"] and ok["identical_output_share"] == 1.0 and ok["compared_items"] == 20

    bad = served_check.compare(tmp_path / "examples.jsonl", tmp_path / "reference.jsonl", tmp_path / "broken.jsonl")
    assert not bad["passed"] and bad["identical_output_share"] == 0.0
    assert any("valid-output rate" in f for f in bad["failures"])


def test_join_pairs_repeated_ids_in_order(tmp_path):
    """Data prepared before 28 Oct 2026 repeats Prometheus unseen-rubric test ids; scoring
    must pair each prediction with its own example, not the last example with that id."""
    from evaltrain import evaluate

    exs = _examples(6)
    for e in exs[:3]:
        e.id = "oak:dup"  # three rows share one id, with gold scores 1, 2, 3
    write_jsonl(tmp_path / "examples.jsonl", exs)
    write_jsonl(tmp_path / "preds.jsonl", _predictions(exs))  # one prediction per row, in order
    rows, coverage = evaluate.join(tmp_path / "examples.jsonl", tmp_path / "preds.jsonl")
    oak = rows["oak_distractors"]
    assert [r["id"] for r in oak[:3]] == ["oak:dup#0", "oak:dup#1", "oak:dup#2"]
    assert all(r["pred"]["score"] == r["gold"]["score"] for r in oak)  # every prediction met its own gold
    assert coverage["oak_distractors"]["duplicate_example_ids"] == 2 and coverage["oak_distractors"]["predicted"] == 6


def test_smaller_eval_subsample_is_nested_in_larger_one():
    from evaltrain.run_eval import subsample_by_group

    exs = [Example(id=f"x:{i}", task="t", dataset="d", split="dev", group=f"g{i % 9}", messages=[], target=None, gold={}) for i in range(300)]
    small = {e.id for e in subsample_by_group(exs, 40)}
    large = {e.id for e in subsample_by_group(exs, 120)}
    assert small < large and {e.group for e in exs if e.id in small} == {e.group for e in exs}


def test_served_check_subset_is_deterministic_per_task():
    exs = _examples(40)
    first = [e.id for e in served_check.pick(exs, 7)]
    assert first == [e.id for e in served_check.pick(list(reversed(exs)), 7)]
    assert len(first) == 7


def _finished_run(root, effect: dict):
    run = root / "runs" / "pilot"
    (run / "train").mkdir(parents=True)
    (run / "train" / TRAINING_DONE_MARKER).write_text("{}")
    (run / "adapter").mkdir()
    for name in promote.ADAPTER_FILES:
        (run / "adapter" / name).write_text("{}" if name.endswith(".json") else "weights")
    evaluation = run / "eval" / "adapter-dev"
    evaluation.mkdir(parents=True)
    (evaluation / "examples.jsonl").write_text("")
    (evaluation / "predictions.jsonl").write_text("")
    (evaluation / "report.json").write_text(json.dumps({"tasks": {"oak_distractors": {"ci": {"mae": {"value": 0.8}}}}, "adapter_effect": effect}))
    (run / "run.json").write_text(json.dumps({"run_id": "pilot", "training_hash": "abc", "code_sha256": "def"}))
    return run


def test_promote_copies_adapter_and_reference(tmp_path):
    run = _finished_run(tmp_path, {"checked": True, "identical_share": 0.0})
    dest = promote.promote(run, tmp_path / "bundle", "reviewer-v1")
    assert {p.name for p in dest.iterdir()} == {*promote.ADAPTER_FILES, "reference", "PROMOTED.json"}
    assert {p.name for p in (dest / "reference").iterdir()} == set(promote.REFERENCE_FILES)
    record = json.loads((dest / "PROMOTED.json").read_text())
    assert record["training_hash"] == "abc" and record["reference_metrics"] == {"oak_distractors": {"mae": 0.8}} and record["forced_past"] == []
    with pytest.raises(SystemExit, match="already exists"):
        promote.promote(run, tmp_path / "bundle", "reviewer-v1")


def test_promote_refuses_unapplied_or_unevaluated_adapters(tmp_path):
    run = _finished_run(tmp_path, {"checked": True, "identical_share": 1.0, "warning": "adapter outputs match the base model"})
    with pytest.raises(SystemExit, match="adapter outputs match"):
        promote.promote(run, tmp_path / "bundle", "reviewer-v1")
    forced = promote.promote(run, tmp_path / "bundle", "reviewer-v1", force=True)
    assert json.loads((forced / "PROMOTED.json").read_text())["forced_past"]  # the override is on record

    (run / "eval" / "adapter-dev" / "predictions.jsonl").unlink()
    (run / "train" / TRAINING_DONE_MARKER).unlink()
    problems = promote.check(run, "dev")
    assert any("not completed" in p for p in problems) and any("missing" in p for p in problems)
