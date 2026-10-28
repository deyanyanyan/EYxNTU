from __future__ import annotations

import math

import pytest

from evaltrain.parsing import as_score, expected_score, extract_json, score_distributions


def test_extract_json_strict_lenient_and_thinking():
    assert extract_json('{"score": 4}') == ({"score": 4}, True, None)
    assert extract_json('<think>\nhmm {"score": 1}\n</think>\n\n{"score": 4}') == ({"score": 4}, True, None)
    obj, strict, err = extract_json('```json\n{"score": 2}\n```')
    assert obj == {"score": 2} and not strict and err is None
    obj, strict, _ = extract_json('Here you go: {"feedback": "ok {fine}", "score": 3} thanks')
    assert obj == {"feedback": "ok {fine}", "score": 3} and not strict
    assert extract_json("no json here")[0] is None
    assert extract_json("[1, 2]")[0] is None


def test_score_distribution_at_score_digit():
    pieces = ['{"', "feedback", '":', ' "', "Good", ' 4', ' points', '",', ' "', "score", '":', " ", "4", "}"]
    top = [[] for _ in pieces]
    # The digit inside the feedback text must be ignored; only the one after "score": counts.
    top[5] = [(" 4", 0.0)]
    top[12] = [("4", math.log(0.6)), ("3", math.log(0.2)), ("5", math.log(0.1)), ("x", math.log(0.1))]
    dist = score_distributions(pieces, top, ["score"])
    assert set(dist) == {"score"}
    assert dist["score"]["4"] == pytest.approx(0.6 / 0.9)
    assert expected_score(dist["score"]) == pytest.approx((4 * 0.6 + 3 * 0.2 + 5 * 0.1) / 0.9)


def test_score_distribution_sums_duplicate_texts_and_multiple_keys():
    pieces = ['{"', "clarity", '":', " ", "3", ', "', "structure", '": ', "5", "}"]
    top = [[] for _ in pieces]
    top[4] = [("3", math.log(0.25)), ("3", math.log(0.25)), ("2", math.log(0.5))]
    top[8] = [("5", 0.0)]
    dist = score_distributions(pieces, top, ["clarity", "structure"])
    assert dist["clarity"] == {"2": pytest.approx(0.5), "3": pytest.approx(0.5)}
    assert dist["structure"] == {"5": pytest.approx(1.0)}


def test_as_score():
    assert as_score(4) == 4 and as_score("5") == 5 and as_score(3.0) == 3
    assert as_score(0) is None and as_score(6) is None and as_score(True) is None and as_score(3.5) is None
