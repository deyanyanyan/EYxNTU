"""Prometheus Feedback Collection: rubric-conditioned feedback with a 1-5 score.

Each source row carries the instruction, the response under review, a reference
answer that would score 5, the rubric criterion with five score descriptions, and
GPT-4's feedback and score. The training target is exactly that feedback and score;
the labels are synthetic and reported as agreement with GPT-4, not with people.

Splits:

* train/dev come from Feedback Collection, grouped by connected components over
  instruction *and* rubric, so dev measures generalisation to unseen rubrics;
* test is the pair of held-out sets in the prometheus-eval repository: ``seen_rubric``
  (new instructions, Feedback Collection rubrics) and ``unseen_rubric`` (new rubrics).
  The Hugging Face "Feedback-Bench" dataset is deliberately not used: its 1,000 rows
  are verbatim Feedback Collection rows.

Feedback Collection rows that share an instruction with either test set, or a rubric
with the unseen-rubric set, are removed from train/dev and counted in the record.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from evaltrain import metrics as M
from evaltrain.parsing import as_score, expected_score
from evaltrain.prompts import RUBRIC, chat
from evaltrain.records import Example, dump_target
from evaltrain.splits import assign, audit_leakage, connected_groups, text_key
from evaltrain.tasks import Task

NAME = "prometheus_rubric"
FIELDS = ("instruction", "response", "reference", "criteria", "score1", "score2", "score3", "score4", "score5")
_MARKERS = [
    ("instruction", "###The instruction to evaluate:\n"),
    ("response", "\n\n###Response to evaluate:\n"),
    ("reference", "\n\n###Reference Answer (Score 5):\n"),
    ("criteria", "\n\n###Score Rubrics:\n["),
    ("score1", "]\nScore 1: "),
    ("score2", "\nScore 2: "),
    ("score3", "\nScore 3: "),
    ("score4", "\nScore 4: "),
    ("score5", "\nScore 5: "),
]
_END = "\n\n###Feedback:"


def parse_prompt(text: str) -> dict:
    """Recover the fields of a pre-rendered Prometheus absolute-grading prompt."""
    starts = []
    pos = 0
    for name, marker in _MARKERS:
        i = text.index(marker, pos)
        starts.append((name, i, i + len(marker)))
        pos = i + len(marker)
    end = text.rindex(_END)
    out = {}
    for k, (name, _, body_start) in enumerate(starts):
        body_end = starts[k + 1][1] if k + 1 < len(starts) else end
        out[name] = text[body_start:body_end]
    return out


def _from_fc_row(row: dict) -> dict:
    return {
        "instruction": row["orig_instruction"], "response": row["orig_response"], "reference": row["orig_reference_answer"], "criteria": row["orig_criteria"],
        **{f"score{i}": row[f"orig_score{i}_description"] for i in range(1, 6)},
    }


def _rubric_key(f: dict) -> str:
    return text_key("\n".join([f["criteria"], *(f[f"score{i}"] for i in range(1, 6))]))


def _example(ex_id: str, split: str, group: str, f: dict, feedback: str, score: int, subset: str, meta: dict) -> Example:
    user = RUBRIC.format(**f)
    meta = meta | {"instruction_key": text_key(f["instruction"]), "criterion_key": text_key(f["criteria"])}
    return Example(
        id=ex_id, task=NAME, dataset="prometheus", split=split, group=group, messages=chat(user),
        target=dump_target({"feedback": feedback.strip(), "score": score}), gold={"score": score, "subset": subset}, meta=meta,
    )


def build(raw_dir: Path, cfg: dict) -> tuple[list[Example], dict]:
    salt = cfg.get("salt", "evaltrain-v1")
    dev_fraction = cfg.get("prometheus_dev_fraction", 0.05)
    fc = json.loads((raw_dir / "prometheus_fc" / "new_feedback_collection.json").read_text(encoding="utf-8"))
    tests_dir = raw_dir / "prometheus_tests" / "eval" / "benchmark" / "data"
    tests = {
        "seen_rubric": json.loads((tests_dir / "feedback_collection_test.json").read_text(encoding="utf-8")),
        "unseen_rubric": json.loads((tests_dir / "feedback_collection_ood_test.json").read_text(encoding="utf-8")),
    }

    # The parser must reproduce the published fields exactly before it is trusted on the test prompts.
    mismatches = sum(parse_prompt(r["instruction"]) != _from_fc_row(r) for r in fc)
    if mismatches:
        raise ValueError(f"prompt parser disagrees with orig_* fields on {mismatches} Feedback Collection rows")

    test_fields = {name: [parse_prompt(r["instruction"]) for r in rows] for name, rows in tests.items()}
    test_inst = {text_key(f["instruction"]) for fs in test_fields.values() for f in fs}
    unseen_rub = {text_key(f["criteria"]) for f in test_fields["unseen_rubric"]}

    record: dict = {"source_rows": len(fc), "dropped": Counter(), "test_rows": {k: len(v) for k, v in tests.items()}}
    kept = []
    for i, r in enumerate(fc):
        f = _from_fc_row(r)
        if not f["response"].strip() or not f["reference"].strip():
            record["dropped"]["empty_response_or_reference"] += 1
        elif text_key(f["instruction"]) in test_inst:
            record["dropped"]["instruction_in_test"] += 1
        elif text_key(f["criteria"]) in unseen_rub:
            record["dropped"]["criterion_in_unseen_rubric_test"] += 1
        else:
            kept.append((i, r, f))

    groups = connected_groups((str(i), [f"inst:{text_key(f['instruction'])}", f"rub:{_rubric_key(f)}", f"crit:{text_key(f['criteria'])}"]) for i, _, f in kept)
    sizes = Counter(groups.values())
    examples = []
    for i, r, f in kept:
        g = groups[str(i)]
        split = assign(g, salt, {"train": 1 - dev_fraction, "dev": dev_fraction})
        examples.append(_example(f"prometheus:fc:{i}", split, f"prometheus:{g}", f, r["orig_feedback"], int(r["orig_score"]),
                                 "dev_unseen_rubric" if split == "dev" else "train", {"source": "prometheus_fc", "row": i, "label_origin": "gpt-4"}))

    for name, rows in tests.items():
        fields = test_fields[name]
        tgroups = connected_groups((str(k), [f"inst:{text_key(f['instruction'])}", f"rub:{_rubric_key(f)}"]) for k, f in enumerate(fields))
        for k, (r, f) in enumerate(zip(rows, fields, strict=True)):
            # The files' own `idx` is not unique (the unseen-rubric file numbers rows per
            # instruction, 5 responses each), so the id uses the row position; `file_idx` keeps it.
            examples.append(_example(f"prometheus:{name}:{k}", "test", f"prometheus:{name}:{tgroups[str(k)]}", f, r["gpt4_feedback"], int(r["gpt4_score"]),
                                     name, {"source": "prometheus_tests", "file_idx": r["idx"], "file_row": k, "label_origin": "gpt-4"}))

    by_split = defaultdict(list)
    for e in examples:
        by_split[e.split].append(e)
    record |= {
        "dropped": dict(record["dropped"]), "kept_fc_rows": len(kept), "fc_groups": len(sizes), "largest_fc_group_rows": max(sizes.values()),
        "split_rows": {s: len(v) for s, v in sorted(by_split.items())}, "split_groups": {s: len({e.group for e in v}) for s, v in sorted(by_split.items())},
        "score_counts": {s: dict(sorted(Counter(e.gold["score"] for e in v).items())) for s, v in sorted(by_split.items())},
        "parser_roundtrip_mismatches": mismatches,
    }
    record["leakage"] = {
        "all_splits": audit_leakage(
            [{"split": e.split, "group": e.group, "inst": e.meta["instruction_key"]} for e in examples],
            {"group": lambda r: [r["group"]], "instruction": lambda r: [r["inst"]]},
        ),
        # The seen-rubric test shares rubrics with Feedback Collection by design; every other partition must not.
        "criterion_except_seen_rubric_test": audit_leakage(
            [{"split": e.split, "crit": e.meta["criterion_key"]} for e in examples if e.gold["subset"] != "seen_rubric"],
            {"criterion": lambda r: [r["crit"]]},
        ),
    }
    return examples, record


def parse(obj: dict) -> dict:
    score = as_score(obj.get("score"))
    if score is None:
        raise ValueError(f"score must be an integer 1-5, got {obj.get('score')!r}")
    feedback = obj.get("feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        raise ValueError("feedback must be a non-empty string")
    return {"score": score, "feedback": feedback}


def _pairs(rows: list[dict], expected: bool = False) -> tuple[list[float], list[float]]:
    gold, pred = [], []
    for r in rows:
        if r["pred"] is None:
            continue
        if expected:
            dist = r["dist"].get("score")
            if not dist:
                continue
            pred.append(expected_score(dist))
        else:
            pred.append(r["pred"]["score"])
        gold.append(r["gold"]["score"])
    return gold, pred


def point_metrics(rows: list[dict]) -> dict:
    out = {}
    for subset in sorted({r["gold"]["subset"] for r in rows}) + ["all"]:
        sub = [r for r in rows if subset == "all" or r["gold"]["subset"] == subset]
        g, p = _pairs(sub)
        ge, pe = _pairs(sub, expected=True)
        rep = M.ordinal_report(g, p)
        if pe and len(pe) == len(p):
            rep |= {k: v for k, v in M.ordinal_report(ge, p, pe).items() if k.endswith("_expected")}
        out[subset] = rep | {"n_rows": len(sub), "n_valid": len(p)}
    return out


def _strict_exact(rows: list[dict]) -> float:
    """Exact agreement counting unparseable outputs as wrong."""
    return sum(r["pred"] is not None and r["pred"]["score"] == r["gold"]["score"] for r in rows) / max(len(rows), 1)


TASK = Task(
    name=NAME,
    dataset="prometheus",
    build=build,
    parse=parse,
    point_metrics=point_metrics,
    ci_metrics={
        "pearson": lambda rs: M.pearson(*_pairs(rs)),
        "spearman": lambda rs: M.spearman(*_pairs(rs)),
        "exact_all_rows": _strict_exact,
        "mae": lambda rs: M.mae(*_pairs(rs)),
    },
    score_keys=("score",),
    max_new_tokens=512,
)
