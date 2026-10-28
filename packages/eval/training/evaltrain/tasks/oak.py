"""Oak National Academy MCQ MinDiff: teacher scores (1-5) for how minimally different
a question's distractors are from its correct answer.

The construct is narrower than "distractor quality": 5 means the options differ
subtly enough to test deeper understanding while staying fair; 1 means the correct
answer is obvious. The rubric anchors below are Oak's original judge wording
(oak-dspy-mcq-eval, prompts/mcq_mindiff_original.txt, MIT). Targets are the
``human_score`` only; the file's baseline LLM scores are kept as a reference point,
never as labels.

The split reproduces the repository's ``_stratified_split`` exactly (seed 1337,
20/60/20 within each score, giving 61 demonstration / 185 development / 65 test
rows) and is checked against the published counts and the first indices. Its 61
demonstration rows are the only rows a later adaptation may train on. Rows outside
the test partition whose question duplicates a test question are dropped, so the
test partition itself is never altered.
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from evaltrain import metrics as M
from evaltrain.parsing import as_score, expected_score
from evaltrain.prompts import DISTRACTORS, chat
from evaltrain.records import Example, dump_target
from evaltrain.splits import audit_leakage, text_key
from evaltrain.tasks import Task

NAME = "oak_distractors"
RUBRIC_TEXT = """Judge whether the correct answer and the distractors are minimally different from each other: whether the question subtly tests deeper understanding of the topic by making the correct answer only slightly more accurate than the distractors, while the differences remain sufficient to test knowledge accurately without being trivial or overly ambiguous.
5 (Minimally Distinct): The correct answers and distractors are subtly different, effectively assessing deeper understanding and discernment skills without being obvious, while still ensuring each question is valid and distinct enough to be fair.
1 (Clearly Distinct): The correct answers and distractors are clearly and easily distinguishable, which may not effectively challenge the student's deeper understanding or discernment skills.
Scores 2 to 4 lie between these anchors."""

EXPECTED_COUNTS = {"train": 61, "dev": 185, "test": 65}
EXPECTED_FIRST = {"train": [30, 1, 18, 300, 32, 277, 8, 17, 4, 304], "test": [19, 280, 24, 21, 10, 238, 237, 23, 34, 248]}


def oak_split(rows: list[dict], seed: int = 1337, train_ratio: float = 0.2, dev_ratio: float = 0.6) -> dict[str, list[int]]:
    """Plain-Python port of ``mcq_eval.judges.mcq_mindiff_data._stratified_split``.

    The original calls ``random.seed(seed)`` and shuffles the global generator; a fresh
    ``random.Random(seed)`` produces the identical sequence. Groups are shuffled in
    first-appearance order and allocated in sorted score order, as in the original.
    """
    rnd = random.Random(seed)
    by_score: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_score[r["human_score"]].append(i)
    for score in by_score:
        rnd.shuffle(by_score[score])
    out: dict[str, list[int]] = {"train": [], "dev": [], "test": []}
    for score in sorted(by_score):
        idx = by_score[score]
        n = len(idx)
        train_end = int(n * train_ratio)
        dev_end = train_end + int(n * dev_ratio)
        out["train"] += idx[:train_end]
        out["dev"] += idx[train_end:dev_end]
        out["test"] += idx[dev_end:]
    return out


def _question_key(r: dict) -> str:
    return text_key(r["question"])


def build(raw_dir: Path, cfg: dict) -> tuple[list[Example], dict]:
    rows = json.loads((raw_dir / "oak" / "data" / "mcq_mindiff_dataset.json").read_text(encoding="utf-8"))
    parts = oak_split(rows)
    counts = {k: len(v) for k, v in parts.items()}
    if counts != EXPECTED_COUNTS or any(parts[k][: len(v)] != v for k, v in EXPECTED_FIRST.items()):
        raise ValueError(f"Oak split does not reproduce the repository split: {counts}")
    split_of = {i: name for name, idx in parts.items() for i in idx}
    test_questions = {_question_key(rows[i]) for i in parts["test"]}

    record: dict = {"source_rows": len(rows), "reproduced_split": counts, "dropped": Counter(), "distractor_counts": dict(Counter(len(r["distractors"]) for r in rows))}
    examples = []
    for i, r in enumerate(rows):
        split = split_of[i]
        qk = _question_key(r)
        if split != "test" and qk in test_questions:
            record["dropped"][f"{split}_duplicates_test_question"] += 1
            continue
        score = int(r["human_score"])
        user = DISTRACTORS.format(rubric=RUBRIC_TEXT, question=r["question"].strip(), answer=r["correct_answer"].strip(), distractors="\n".join(f"- {d.strip()}" for d in r["distractors"]))
        examples.append(
            Example(
                id=f"oak:{i}", task=NAME, dataset="oak", split=split, group=f"oak:{qk}", messages=chat(user), target=dump_target({"score": score}),
                gold={"score": score, "subset": split, "reference_llm_post": r.get("baseline_post_mse_score"), "reference_llm_pre": r.get("baseline_pre_mse_score")},
                meta={"source": "oak", "row": i, "label_origin": "human teacher score", "question_key": qk},
            )
        )
    by_split = defaultdict(list)
    for e in examples:
        by_split[e.split].append(e)
    record |= {
        "dropped": dict(record["dropped"]),
        "split_rows": {k: len(v) for k, v in sorted(by_split.items())},
        "score_counts": {k: dict(sorted(Counter(e.gold["score"] for e in v).items())) for k, v in sorted(by_split.items())},
        "leakage": {"all_splits": audit_leakage([{"split": e.split, "q": e.meta["question_key"]} for e in examples], {"question": lambda r: [r["q"]]})},
    }
    return examples, record


def parse(obj: dict) -> dict:
    score = as_score(obj.get("score"))
    if score is None:
        raise ValueError(f"score must be an integer 1-5, got {obj.get('score')!r}")
    return {"score": score}


def _pairs(rows: list[dict], expected: bool = False):
    g, p = [], []
    for r in rows:
        if r["pred"] is None:
            continue
        if expected:
            d = r["dist"].get("score")
            if not d:
                continue
            p.append(expected_score(d))
        else:
            p.append(r["pred"]["score"])
        g.append(r["gold"]["score"])
    return g, p


def point_metrics(rows: list[dict]) -> dict:
    g, p = _pairs(rows)
    ge, pe = _pairs(rows, expected=True)
    rep = M.ordinal_report(g, p) | {"n_rows": len(rows), "n_valid": len(p)}
    if pe and len(pe) == len(p):
        rep |= {k: v for k, v in M.ordinal_report(ge, p, pe).items() if k.endswith("_expected")}
    ref = [(r["gold"]["score"], r["gold"]["reference_llm_post"]) for r in rows if r["gold"].get("reference_llm_post") is not None]
    if ref:
        rep["reference_oak_llm_post_mae"] = M.mae([a for a, _ in ref], [b for _, b in ref])
        rep["reference_oak_llm_post_spearman"] = M.spearman([a for a, _ in ref], [b for _, b in ref])
    return rep


TASK = Task(
    name=NAME,
    dataset="oak",
    build=build,
    parse=parse,
    point_metrics=point_metrics,
    ci_metrics={
        "mae": lambda rs: M.mae(*_pairs(rs)),
        "spearman": lambda rs: M.spearman(*_pairs(rs)),
        "qwk": lambda rs: M.quadratic_weighted_kappa(*_pairs(rs)),
    },
    score_keys=("score",),
    max_new_tokens=16,
)
