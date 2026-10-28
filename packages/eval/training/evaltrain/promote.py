"""Copy a finished, evaluated adapter into the deployment model bundle.

    python -m evaltrain.promote --run $EVALTRAIN_ROOT/runs/pilot-9b-v1 --name reviewer-pilot-9b-v1 --dest data/models/adapters

Copies the exported serving adapter (weights, adapter config, serving.json) to
``<dest>/<name>/`` and the adapter's development-split evaluation (examples,
predictions, report) to ``<dest>/<name>/reference/``, which ``evaltrain.served_check``
replays against the deployed server. Refuses a run that has not finished training, has
no adapter evaluation, or whose evaluation found that the adapter was probably not
applied. Bundles are immutable once locked, so an existing name is never overwritten.
Record the result with ``make models-lock`` afterwards.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from evaltrain.callbacks import TRAINING_DONE_MARKER

ADAPTER_FILES = ("adapter_model.safetensors", "adapter_config.json", "serving.json")
REFERENCE_FILES = ("examples.jsonl", "predictions.jsonl", "report.json")


def check(run: Path, split: str) -> list[str]:
    problems = []
    if not (run / "train" / TRAINING_DONE_MARKER).exists():
        problems.append("training has not completed (no TRAINING_COMPLETE.json)")
    missing = [f for f in ADAPTER_FILES if not (run / "adapter" / f).is_file()]
    if missing:
        problems.append(f"the exported adapter is missing {missing}")
    evaluation = run / "eval" / f"adapter-{split}"
    missing = [f for f in REFERENCE_FILES if not (evaluation / f).is_file()]
    if missing:
        problems.append(f"the adapter evaluation is missing {missing}: run the adapter arm first")
    else:
        effect = json.loads((evaluation / "report.json").read_text(encoding="utf-8")).get("adapter_effect", {})
        if effect.get("warning"):
            problems.append(f"the adapter evaluation warns: {effect['warning']}")
        elif not effect.get("checked"):
            problems.append("the adapter evaluation could not check that the adapter was applied (evaluate the base arm too)")
    return problems


def promote(run: Path, dest_root: Path, name: str, split: str = "dev", force: bool = False) -> Path:
    problems = check(run, split)
    if problems and not force:
        raise SystemExit("not promoting " + str(run) + ":\n  " + "\n  ".join(problems))
    dest = dest_root / name
    if dest.exists():
        raise SystemExit(f"{dest} already exists: promote under a new name (locked bundles are immutable)")
    (dest / "reference").mkdir(parents=True)
    for f in ADAPTER_FILES:
        shutil.copy2(run / "adapter" / f, dest / f)
    evaluation = run / "eval" / f"adapter-{split}"
    for f in REFERENCE_FILES:
        shutil.copy2(evaluation / f, dest / "reference" / f)
    record = json.loads((run / "run.json").read_text(encoding="utf-8")) if (run / "run.json").exists() else {}
    report = json.loads((evaluation / "report.json").read_text(encoding="utf-8"))
    promoted = {
        "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_run": record.get("run_id", run.name),
        "training_hash": record.get("training_hash"),
        "code_sha256": record.get("code_sha256"),
        "git_revision": record.get("git_revision"),
        "reference_split": split,
        "reference_metrics": {task: {k: ci["value"] for k, ci in entry.get("ci", {}).items()} for task, entry in report.get("tasks", {}).items()},
        "forced_past": problems,
    }
    (dest / "PROMOTED.json").write_text(json.dumps(promoted, indent=2), encoding="utf-8")
    return dest


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="run directory, e.g. $EVALTRAIN_ROOT/runs/pilot-9b-v1")
    ap.add_argument("--name", required=True, help="bundle directory name, e.g. reviewer-pilot-9b-v1")
    ap.add_argument("--dest", default="data/models/adapters")
    ap.add_argument("--split", default="dev", help="which adapter evaluation to carry as the reference")
    ap.add_argument("--force", action="store_true", help="promote despite failed checks (recorded in PROMOTED.json)")
    args = ap.parse_args(argv)
    dest = promote(Path(args.run), Path(args.dest), args.name, args.split, args.force)
    print(f"promoted to {dest}; next: make models-lock, then make served-check against the running server")


if __name__ == "__main__":
    main()
