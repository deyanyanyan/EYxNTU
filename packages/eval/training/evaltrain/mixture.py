"""Bounded, task-balanced training mixtures.

A mixture is a deterministic function of the prepared train split and the experiment
config. For each task, train examples are ranked by a salted hash of their id and taken
in that order, with an optional cap per group so one instruction or source document
cannot dominate, and an optional ``repeat`` to replay small educational tasks next to
the large general one. Examples the length profile marked as over-length are excluded
and counted, never truncated.

The output is MS-SWIFT's standard ``messages`` JSONL with the published label as the
assistant turn. ``mixture.json`` beside it records counts, selected-id hash and input
file hashes; ``train.py`` refuses to resume when they no longer match.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from evaltrain.records import Example, read_examples, sha256_file, write_jsonl
from evaltrain.splits import bucket


def select(examples: list[Example], n: int | None, per_group_cap: int | None, salt: str, exclude: set[str]) -> tuple[list[Example], int]:
    ranked = sorted(examples, key=lambda e: bucket(e.id, salt))
    chosen: list[Example] = []
    per_group: Counter[str] = Counter()
    excluded = 0
    for e in ranked:
        if e.id in exclude:
            excluded += 1
            continue
        if per_group_cap and per_group[e.group] >= per_group_cap:
            continue
        chosen.append(e)
        per_group[e.group] += 1
        if n and len(chosen) >= n:
            break
    return chosen, excluded


def to_swift_row(e: Example, image_root: Path | None = None) -> dict:
    """MS-SWIFT row; images get the ``<image>`` placeholders MS-SWIFT expects, ahead of the
    user text (the same position the inference backends place the image parts)."""
    if e.target is None:
        raise ValueError(f"{e.id} has no training target")
    msgs = [dict(m) for m in e.messages]
    if e.images:
        msgs[-1]["content"] = "<image>" * len(e.images) + msgs[-1]["content"]
    row = {"messages": [*msgs, {"role": "assistant", "content": e.target}]}
    if e.images:
        row["images"] = [str((image_root / p) if image_root else p) for p in e.images]
    return row


def build(prepared_dir: str | Path, mixture: dict, out_path: str | Path, salt: str, seed: int, overlength_ids: set[str] | None = None, image_root: Path | None = None) -> dict:
    prepared_dir, out_path = Path(prepared_dir), Path(out_path)
    rows, record = [], {"salt": salt, "seed": seed, "tasks": {}}
    for task, spec in mixture.items():
        src = prepared_dir / f"{task}.train.jsonl"
        exs = read_examples(src)
        bad = [e.id for e in exs if e.split != "train"]
        if bad:
            raise ValueError(f"{src} contains non-train rows, e.g. {bad[:3]}")
        chosen, excluded = select(exs, spec.get("n"), spec.get("per_group_cap"), salt, overlength_ids or set())
        repeat = int(spec.get("repeat", 1))
        task_rows = [to_swift_row(e, image_root) for e in chosen] * repeat
        rows += task_rows
        ids = sorted(e.id for e in chosen)
        record["tasks"][task] = {
            "available": len(exs), "selected": len(chosen), "repeat": repeat, "rows": len(task_rows), "excluded_overlength": excluded,
            "groups": len({e.group for e in chosen}), "ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(), "source_sha256": sha256_file(src),
        }
    random.Random(seed).shuffle(rows)
    record["rows"] = write_jsonl(out_path, rows)
    record["file_sha256"] = sha256_file(out_path)
    out_path.with_name("mixture.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
