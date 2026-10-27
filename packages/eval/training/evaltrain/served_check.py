"""Release gate: does the deployed server reproduce the adapter's cluster evaluation?

    python -m evaltrain.served_check --adapter-dir data/models/adapters/reviewer-pilot-9b-v1 \
        --base-url http://127.0.0.1:8001/v1 --model reviewer

Sends a deterministic subset of the adapter's reference examples (copied in by
``evaltrain.promote``) to the running OpenAI-compatible server with the settings the
adapter was evaluated with (greedy decoding, thinking off), scores the replies and
compares them with the reference predictions on the same items. A wrong chat
template, thinking left on, an adapter that silently failed to load, a different base
revision or damaging quantization all show up as moved metrics or mostly different
outputs. Exit code 0 means the deployment serves the model that was evaluated.

Replies are compared on the same items, so the tolerance only has to absorb numerical
differences between GPUs and batch sizes, not sampling noise.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from evaltrain import evaluate, infer
from evaltrain.records import Example, read_examples, read_jsonl, write_jsonl
from evaltrain.splits import bucket


def pick(examples: list[Example], per_task: int) -> list[Example]:
    by_task: dict[str, list[Example]] = defaultdict(list)
    for e in examples:
        by_task[e.task].append(e)
    return [e for task in sorted(by_task) for e in sorted(by_task[task], key=lambda e: bucket(e.id, "served-check"))[:per_task]]


def compare(examples_path: Path, reference_path: Path, served_path: Path, tolerance: float = 0.05, max_valid_drop: float = 0.02) -> dict:
    ids = {e.id for e in read_examples(examples_path)}
    reference = evaluate.evaluate(examples_path, reference_path, n_boot=0)
    served = evaluate.evaluate(examples_path, served_path, n_boot=0)
    ref_raw = {r["id"]: r.get("raw") for r in read_jsonl(reference_path) if r["id"] in ids}
    pairs = [(ref_raw[r["id"]], r.get("raw")) for r in read_jsonl(served_path) if r["id"] in ref_raw]
    failures, tasks = [], {}
    for task, ref in reference["tasks"].items():
        got = served["tasks"].get(task)
        if got is None:
            failures.append(f"{task}: no served predictions")
            continue
        if got["coverage"]["predicted"] < got["coverage"]["expected"]:
            failures.append(f"{task}: served {got['coverage']['predicted']}/{got['coverage']['expected']} items")
        valid_drop = ref["valid_rate"] - got["valid_rate"]
        if valid_drop > max_valid_drop:
            failures.append(f"{task}: valid-output rate fell from {ref['valid_rate']:.3f} to {got['valid_rate']:.3f}")
        deltas = {}
        for metric, ci in ref["ci"].items():
            a, b = ci["value"], got["ci"].get(metric, {}).get("value", math.nan)
            deltas[metric] = {"reference": a, "served": b, "delta": b - a}
            if a == a and (b != b or abs(b - a) > tolerance):
                failures.append(f"{task}: {metric} {a:.3f} -> {b:.3f} (tolerance {tolerance})")
        tasks[task] = {"valid_rate": {"reference": ref["valid_rate"], "served": got["valid_rate"]}, "metrics": deltas}
    identical = sum(a == b for a, b in pairs) / len(pairs) if pairs else math.nan
    return {"passed": not failures, "failures": failures, "identical_output_share": identical, "compared_items": len(pairs), "tolerance": tolerance, "tasks": tasks}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter-dir", required=True, help="bundle directory with reference/ (from evaltrain.promote)")
    ap.add_argument("--base-url", required=True, help="the deployed OpenAI-compatible endpoint, e.g. http://127.0.0.1:8001/v1")
    ap.add_argument("--model", required=True, help="served model name of the adapter, e.g. reviewer")
    ap.add_argument("--per-task", type=int, default=50, help="reference items replayed per task")
    ap.add_argument("--tolerance", type=float, default=0.05, help="largest allowed change of any task metric")
    ap.add_argument("--out-dir", default="data/artifacts/served-check")
    args = ap.parse_args(argv)

    adapter_dir = Path(args.adapter_dir)
    reference = adapter_dir / "reference"
    chosen = pick(read_examples(reference / "examples.jsonl"), args.per_task)
    out = Path(args.out_dir) / f"{adapter_dir.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    write_jsonl(out / "examples.jsonl", chosen)
    backend = infer.OpenAIBackend(args.base_url, args.model, thinking=False)
    infer.run(chosen, out / "served.jsonl", backend, batch_size=1, thinking=False, extra_think_tokens=0, image_root=None, deadline=None)
    report = compare(out / "examples.jsonl", reference / "predictions.jsonl", out / "served.jsonl", args.tolerance)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"identical outputs: {report['identical_output_share']:.3f} over {report['compared_items']} items")
    for task, entry in report["tasks"].items():
        moved = ", ".join(f"{k} {v['reference']:.3f}->{v['served']:.3f}" for k, v in entry["metrics"].items())
        print(f"  {task}: valid {entry['valid_rate']['reference']:.3f}->{entry['valid_rate']['served']:.3f}; {moved}")
    if not report["passed"]:
        raise SystemExit("served-check FAILED:\n  " + "\n  ".join(report["failures"]) + f"\n(details in {out / 'report.json'})")
    print(f"served-check passed (details in {out / 'report.json'})")


if __name__ == "__main__":
    main()
