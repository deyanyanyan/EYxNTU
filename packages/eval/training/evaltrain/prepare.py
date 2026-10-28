"""Raw public datasets -> split review examples, leakage audits and a data record.

    python -m evaltrain.prepare --raw $EVALTRAIN_ROOT/raw --out $EVALTRAIN_ROOT/prepared/v1
    python -m evaltrain.prepare ... --tasks prometheus_rubric ragtruth_grounding oak_distractors leceval_slides

Writes ``<task>.<split>.jsonl`` for every task and split, ``data_record.json`` (source
manifest, settings, per-task conversion record, split counts, leakage audits, prompt
version) and ``examples.md`` (one rendered example per task and split, for reading the
exact inputs and targets). Fails if any audit finds a grouping key in two splits.
The conversion is deterministic: the same raw files and settings give byte-identical
outputs, which ``data_record.json`` records as checksums.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from evaltrain import tasks as T
from evaltrain.prompts import PROMPT_VERSION, TEMPLATES
from evaltrain.records import sha256_file, write_jsonl
from evaltrain.splits import has_violations

DEFAULT_TASKS = ("prometheus_rubric", "ragtruth_grounding", "oak_distractors")
SETTINGS = {"salt": "evaltrain-v1", "prometheus_dev_fraction": 0.05, "ragtruth_dev_fraction": 0.10, "leceval_fractions": {"train": 0.7, "dev": 0.15, "test": 0.15}}


def _show(text: str, keep: int = 1200) -> str:
    return text if len(text) <= 2 * keep else text[:keep] + f"\n[... {len(text) - 2 * keep} characters omitted in this display only ...]\n" + text[-keep:]


def prepare(raw: Path, out: Path, task_names: list[str]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    sources = json.loads((raw / "sources.json").read_text()) if (raw / "sources.json").exists() else None
    record = {"prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "prompt_version": PROMPT_VERSION, "templates": TEMPLATES, "settings": SETTINGS, "sources": sources, "tasks": {}}
    md = ["# Prepared review examples", "", f"Prompt version `{PROMPT_VERSION}`. One example per task and split; long inputs are shortened in this display only.", ""]
    failures = []
    for name in task_names:
        task = T.get(name)
        t0 = time.time()
        examples, task_record = task.build(raw, SETTINGS)
        # Ids key inference resumption and scoring: a repeated id would skip or mis-pair rows.
        seen_ids: set[str] = set()
        repeated = [e.id for e in examples if e.id in seen_ids or seen_ids.add(e.id)]
        if repeated:
            raise SystemExit(f"{name}: {len(repeated)} repeated example ids, e.g. {repeated[:3]}")
        by_split = defaultdict(list)
        for e in examples:
            by_split[e.split].append(e)
        files = {}
        for split, exs in sorted(by_split.items()):
            path = out / f"{name}.{split}.jsonl"
            write_jsonl(path, exs)
            files[split] = {"file": path.name, "rows": len(exs), "sha256": sha256_file(path)}
            e = exs[0]
            md += [f"## {name} / {split} — `{e.id}`", "", "System:", "", f"````text\n{e.messages[0]['content']}\n````", "", "User:", "",
                   f"````text\n{_show(e.messages[1]['content'])}\n````", ""]
            if e.images:
                md += [f"Images: {', '.join(e.images)}", ""]
            md += ["Target (assistant):" if e.target else "Target: none (scored against gold)", "", f"````json\n{e.target or json.dumps(e.gold)[:600]}\n````", ""]
        for audit_name, audit in task_record.get("leakage", {}).items():
            if has_violations(audit):
                failures.append(f"{name}/{audit_name}: {json.dumps(audit['violations'])[:400]}")
        task_record |= {"files": files, "seconds": round(time.time() - t0, 1), "label_origin": examples[0].meta.get("label_origin") if examples else None}
        record["tasks"][name] = task_record
        print(f"[prepare] {name}: " + ", ".join(f"{s}={f['rows']}" for s, f in files.items()) + f" ({task_record['seconds']}s)")
    (out / "data_record.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    (out / "examples.md").write_text("\n".join(md), encoding="utf-8")
    if failures:
        raise SystemExit("leakage audit failed:\n  " + "\n  ".join(failures))
    return record


def verify(prepared: Path, record_path: Path) -> list[str]:
    """Compare prepared files with the checksums in a data record (e.g. manifests/v1)."""
    record = json.loads(record_path.read_text(encoding="utf-8"))
    problems = []
    for entry in record["tasks"].values():
        for f in entry["files"].values():
            path = prepared / f["file"]
            if not path.exists():
                problems.append(f"missing {path.name}")
            elif sha256_file(path) != f["sha256"]:
                problems.append(f"checksum differs: {path.name}")
    return problems


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tasks", nargs="*", default=list(DEFAULT_TASKS))
    ap.add_argument("--verify", metavar="DATA_RECORD", help="only check --out against this data_record.json, e.g. manifests/v1/data_record.json")
    args = ap.parse_args(argv)
    if args.verify:
        problems = verify(Path(args.out), Path(args.verify))
        if problems:
            raise SystemExit("prepared data does not match the record:\n  " + "\n  ".join(problems))
        print(f"{args.out}: all files match {args.verify}")
        return
    if not args.raw:
        ap.error("--raw is required unless --verify is given")
    prepare(Path(args.raw), Path(args.out), args.tasks)


if __name__ == "__main__":
    main()
