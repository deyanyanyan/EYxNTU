"""Score saved predictions against prepared examples, per task, with grouped CIs.

    python -m evaltrain.evaluate --examples prepared/dev.jsonl --predictions runs/base/preds.jsonl --out report.json
    python -m evaltrain.evaluate --examples prepared/dev.jsonl --predictions base.jsonl --compare adapter.jsonl --out cmp.json

Only examples present in the predictions file are scored, and the report records how
many examples of each task were expected versus predicted, so a partial batch is
visible instead of silently scored as complete.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from evaltrain import metrics as M
from evaltrain import tasks as T
from evaltrain.records import read_examples, read_jsonl


def join(examples_path: str | Path, predictions_path: str | Path) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Pair predictions with examples by id.

    Ids should be unique, but data prepared before 28 Oct 2026 repeats ids in the
    Prometheus unseen-rubric test set (its source numbers rows per instruction). A
    repeated id is matched in order of occurrence: an uninterrupted inference pass writes
    predictions in example order. Such rows get ``<id>#<k>`` row ids, so paired
    comparisons stay aligned, and the coverage record counts them.
    """
    by_id: dict[str, list] = defaultdict(list)
    expected: dict[str, int] = defaultdict(int)
    for e in read_examples(examples_path):
        by_id[e.id].append(e)
        expected[e.task] += 1
    duplicates = sum(len(v) - 1 for v in by_id.values())
    used: dict[str, int] = defaultdict(int)
    rows: dict[str, list[dict]] = defaultdict(list)
    unknown = surplus = 0
    for p in read_jsonl(predictions_path):
        candidates = by_id.get(p["id"])
        if not candidates:
            unknown += 1
            continue
        k = used[p["id"]]
        if k >= len(candidates):
            surplus += 1
            continue
        used[p["id"]] = k + 1
        e = candidates[k]
        row_id = e.id if len(candidates) == 1 else f"{e.id}#{k}"
        rows[e.task].append(
            {"id": row_id, "group": e.group, "gold": e.gold, "pred": p.get("parsed"), "valid": bool(p.get("valid")), "strict": bool(p.get("strict")), "dist": p.get("score_dist") or {}}
        )
    coverage = {
        t: {"expected": n, "predicted": len(rows.get(t, [])), "unknown_prediction_ids": unknown, "surplus_predictions": surplus, "duplicate_example_ids": duplicates}
        for t, n in expected.items()
    }
    return rows, coverage


def evaluate(examples_path, predictions_path, n_boot: int = 1000, seed: int = 0) -> dict:
    rows, coverage = join(examples_path, predictions_path)
    report = {"examples": str(examples_path), "predictions": str(predictions_path), "tasks": {}}
    for name, task_rows in sorted(rows.items()):
        task = T.get(name)
        entry = {
            "coverage": coverage[name],
            "valid_rate": sum(r["valid"] for r in task_rows) / len(task_rows),
            "strict_rate": sum(r["strict"] for r in task_rows) / len(task_rows),
            "metrics": task.point_metrics(task_rows),
            "ci": {k: M.grouped_bootstrap(task_rows, fn, n_boot=n_boot, seed=seed) for k, fn in task.ci_metrics.items()},
        }
        report["tasks"][name] = entry
    return report


def compare(examples_path, base_path, other_path, n_boot: int = 1000, seed: int = 0) -> dict:
    base, _ = join(examples_path, base_path)
    other, _ = join(examples_path, other_path)
    out = {"base": str(base_path), "other": str(other_path), "tasks": {}}
    for name in sorted(set(base) & set(other)):
        task = T.get(name)
        out["tasks"][name] = {k: M.paired_grouped_bootstrap(base[name], other[name], fn, n_boot=n_boot, seed=seed) for k, fn in task.ci_metrics.items()}
    return out


def _fmt(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else (f"{x:.3f}" if isinstance(x, float) else str(x))


def to_markdown(report: dict) -> str:
    lines = []
    for name, entry in report["tasks"].items():
        if "metrics" in entry:
            cov = entry["coverage"]
            lines += [f"### {name}", "", f"Predicted {cov['predicted']}/{cov['expected']}; valid {_fmt(entry['valid_rate'])}, strict JSON {_fmt(entry['strict_rate'])}.", ""]
            lines += ["| Metric | Value | 95% grouped CI |", "|---|---|---|"]
            for k, ci in entry["ci"].items():
                lines.append(f"| {k} | {_fmt(ci['value'])} | {_fmt(ci['ci_low'])} to {_fmt(ci['ci_high'])} ({ci['n_groups']} groups) |")
            for k, v in entry["metrics"].items():
                if k not in entry["ci"] and not isinstance(v, dict):
                    lines.append(f"| {k} | {_fmt(v)} | |")
        else:
            lines += [f"### {name}", "", "| Metric | Difference (other - base) | 95% paired grouped CI |", "|---|---|---|"]
            for k, d in entry.items():
                lines.append(f"| {k} | {_fmt(d['diff'])} | {_fmt(d['ci_low'])} to {_fmt(d['ci_high'])} ({d['n_pairs']} pairs) |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--examples", required=True)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--compare", help="second predictions file: report paired differences against --predictions")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    args = ap.parse_args(argv)
    if args.compare:
        report = compare(args.examples, args.predictions, args.compare, n_boot=args.n_boot)
    else:
        report = evaluate(args.examples, args.predictions, n_boot=args.n_boot)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))


if __name__ == "__main__":
    main()
