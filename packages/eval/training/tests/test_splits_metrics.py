from __future__ import annotations

import math

import pytest

from evaltrain import metrics as M
from evaltrain.splits import assign, audit_leakage, connected_groups, has_violations, text_key


def test_assign_is_deterministic_and_proportional():
    fr = {"train": 0.8, "dev": 0.1, "test": 0.1}
    a = [assign(f"k{i}", "salt", fr) for i in range(20000)]
    assert a == [assign(f"k{i}", "salt", fr) for i in range(20000)]
    assert abs(a.count("train") / len(a) - 0.8) < 0.02
    assert [assign(f"k{i}", "other", fr) for i in range(200)] != a[:200]
    with pytest.raises(ValueError):
        assign("k", "salt", {"train": 0.5})


def test_connected_groups_merges_shared_keys():
    groups = connected_groups([("a", ["inst:1", "rub:x"]), ("b", ["inst:2", "rub:x"]), ("c", ["inst:3", "rub:y"]), ("d", ["inst:2", "rub:z"])])
    assert groups["a"] == groups["b"] == groups["d"] != groups["c"]


def test_audit_flags_cross_split_keys():
    rows = [{"split": "train", "q": "What is X?"}, {"split": "test", "q": "what  is x?"}, {"split": "test", "q": "Other"}]
    audit = audit_leakage(rows, {"question": lambda r: [text_key(r["q"])]})
    assert has_violations(audit) and audit["violations"]["question_total"] == 1


def test_ordinal_metrics():
    gold = [1, 2, 3, 4, 5]
    rep = M.ordinal_report(gold, gold, pred_expected=[1.1, 2.0, 2.9, 4.2, 4.8])
    assert rep["exact"] == 1.0 and rep["qwk"] == pytest.approx(1.0) and rep["spearman_expected"] == pytest.approx(1.0)
    assert math.isnan(M.pearson([3, 3, 3], [1, 2, 3]))


def test_char_span_prf():
    out = M.char_span_prf([[(0, 10)], []], [[(5, 15)], [(0, 5)]])
    assert out["tp"] == 5 and out["fp"] == 10 and out["fn"] == 5
    assert out["precision"] == pytest.approx(1 / 3) and out["recall"] == pytest.approx(0.5)


def test_response_level_prf_and_empty_cases():
    assert M.response_level_prf([True, False, True], [True, True, False])["f1"] == pytest.approx(0.5)
    assert M.prf(0, 0, 3)["f1"] == 0.0
    assert math.isnan(M.prf(0, 0, 0)["f1"])


def test_locate_spans():
    resp = "The fee is $40.\nIt was  raised in 2019. The fee is $40."
    located, missing = M.locate_spans(resp, ["The fee is $40.", "the fee is $40.", "it was raised in 2019", "never said"])
    assert located[0] == (0, 15)
    assert located[1] == (resp.rindex("The fee"), len(resp))
    assert resp[located[2][0] : located[2][1]] == "It was  raised in 2019"
    assert missing == ["never said"]


def test_grouped_bootstrap_brackets_point():
    rows = [{"id": str(i), "group": str(i // 2), "ok": i % 3 != 0} for i in range(60)]
    acc = lambda rs: sum(r["ok"] for r in rs) / len(rs)  # noqa: E731
    out = M.grouped_bootstrap(rows, acc, n_boot=300)
    assert out["ci_low"] <= out["value"] <= out["ci_high"] and out["n_groups"] == 30
    better = [dict(r, ok=True) for r in rows]
    diff = M.paired_grouped_bootstrap(rows, better, acc, n_boot=300)
    assert diff["diff"] > 0 and diff["ci_low"] > 0
