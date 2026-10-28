"""Scorer sanity on the real prepared data: the published labels, fed back as
predictions, must score (near-)perfectly. Skipped unless EVALTRAIN_PREPARED points at a
prepared directory (python -m evaltrain.prepare ...)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evaltrain import evaluate
from evaltrain import tasks as T
from evaltrain.records import read_examples, write_jsonl

PREPARED = os.environ.get("EVALTRAIN_PREPARED")
pytestmark = pytest.mark.skipif(not PREPARED, reason="set EVALTRAIN_PREPARED to a prepared data directory")


def _oracle(ex) -> dict:
    return {"id": ex.id, "task": ex.task, "raw": ex.target, "parsed": T.get(ex.task).parse(json.loads(ex.target)), "valid": True, "strict": True, "score_dist": {}}


@pytest.mark.parametrize("task", ["prometheus_rubric", "ragtruth_grounding", "oak_distractors"])
def test_gold_labels_score_perfectly(task, tmp_path):
    src = Path(PREPARED) / f"{task}.dev.jsonl"
    preds = tmp_path / "oracle.jsonl"
    write_jsonl(preds, [_oracle(e) for e in read_examples(src)])
    rep = evaluate.evaluate(src, preds, n_boot=20)["tasks"][task]
    assert rep["valid_rate"] == 1.0 and rep["coverage"]["predicted"] == rep["coverage"]["expected"]
    m = rep["metrics"]
    if task == "ragtruth_grounding":
        assert m["all"]["response"]["f1"] == 1.0
        assert m["all"]["unlocated_quote_rate"] == 0.0
        # Quotes are mapped to the first unused occurrence; a gold span whose text also
        # occurs earlier in the response can land elsewhere. This is the protocol's ceiling.
        assert m["all"]["span_char"]["f1"] >= 0.98, m["all"]["span_char"]
        print(f"\nRAGTruth oracle span-char F1 (quote-matching ceiling): {m['all']['span_char']['f1']:.4f}")
    elif task == "prometheus_rubric":
        assert m["all"]["exact"] == 1.0 and m["all"]["qwk"] == pytest.approx(1.0)
    else:
        assert m["exact"] == 1.0 and m["mae"] == 0.0
