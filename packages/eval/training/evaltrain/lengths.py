"""Token lengths under the real chat template, and inspectable training renders.

    python -m evaltrain.lengths --prepared $EVALTRAIN_ROOT/prepared/v1 --tokenizer <model dir> --max-length 4096

No silent truncation: every example whose prompt plus target exceeds ``--max-length``
is listed in ``lengths.json`` and excluded from training mixtures, and evaluation
reports flag it, instead of the trainer cutting off evidence or the label.

``render_samples.md`` shows, for a few examples per task, the exact prompt text the
template produces (no loss) and the assistant text that carries the loss, so the
non-thinking prefix and end-of-turn tokens can be inspected before training. MS-SWIFT
applies its own template at training time; ``train.py --dry-run`` prints that render
for comparison.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from evaltrain.records import read_examples


def measure(tok, messages: list[dict], target: str | None, thinking: bool) -> tuple[int, int, str, str]:
    prompt = tok.apply_chat_template(messages, add_generation_prompt=True, enable_thinking=thinking, tokenize=False)
    if target is None:
        return len(tok(prompt, add_special_tokens=False)["input_ids"]), 0, prompt, ""
    full = tok.apply_chat_template([*messages, {"role": "assistant", "content": target}], tokenize=False, enable_thinking=thinking)
    if not full.startswith(prompt):
        # Templates that rewrite earlier turns (e.g. historical thinking) cannot be split
        # at the prompt boundary; fall back to counting the full render as prompt.
        return len(tok(full, add_special_tokens=False)["input_ids"]), 0, full, ""
    completion = full[len(prompt) :]
    n_prompt = len(tok(prompt, add_special_tokens=False)["input_ids"])
    n_completion = len(tok(completion, add_special_tokens=False)["input_ids"])
    return n_prompt, n_completion, prompt, completion


def profile(prepared: Path, tokenizer: str, max_length: int, thinking: bool = False, samples_per_task: int = 2, revision: str | None = None) -> dict:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(tokenizer, revision=revision)
    stats: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    over: list[dict] = []
    renders: dict[str, list[str]] = defaultdict(list)
    for path in sorted(prepared.glob("*.jsonl")):
        if path.name.startswith("mixture") or path.name.startswith("train_"):
            continue
        for e in read_examples(path):
            if e.images:
                continue  # image tokens depend on the processor's resize policy: profiled separately
            n_p, n_c, prompt, completion = measure(tok, e.messages, e.target, thinking)
            key = f"{e.task}.{e.split}"
            stats[key]["total"].append(n_p + n_c)
            stats[key]["completion"].append(n_c)
            if n_p + n_c > max_length:
                over.append({"id": e.id, "task": e.task, "split": e.split, "prompt_tokens": n_p, "completion_tokens": n_c})
            if e.split == "train" and len(renders[e.task]) < samples_per_task:
                renders[e.task].append(_render_block(e.id, prompt, completion, n_p, n_c))
    summary = {
        key: {
            "n": len(v["total"]), "mean": float(np.mean(v["total"])), "p50": int(np.percentile(v["total"], 50)), "p90": int(np.percentile(v["total"], 90)),
            "p99": int(np.percentile(v["total"], 99)), "max": int(max(v["total"])), "completion_p99": int(np.percentile(v["completion"], 99)),
            "over_max_length": sum(t > max_length for t in v["total"]),
        }
        for key, v in sorted(stats.items())
    }
    report = {"tokenizer": tokenizer, "revision": revision, "max_length": max_length, "thinking": thinking, "summary": summary, "over_max_length": over}
    (prepared / "lengths.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    body = ["# Rendered training samples", "", f"Tokenizer: `{tokenizer}`; thinking={thinking}. Loss is computed on the assistant block only.", ""]
    for task, blocks in sorted(renders.items()):
        body += [f"## {task}", "", *blocks]
    (prepared / "render_samples.md").write_text("\n".join(body), encoding="utf-8")
    return report


def _render_block(ex_id: str, prompt: str, completion: str, n_p: int, n_c: int, keep: int = 1500) -> str:
    shown = prompt if len(prompt) <= 2 * keep else prompt[:keep] + f"\n[... {len(prompt) - 2 * keep} characters omitted in this display only ...]\n" + prompt[-keep:]
    return f"### {ex_id}\n\nPrompt, {n_p} tokens, no loss:\n\n````text\n{shown}\n````\n\nAssistant, {n_c} tokens, trained:\n\n````text\n{completion}\n````\n"


def overlength_ids(prepared: Path) -> set[str]:
    path = prepared / "lengths.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `python -m evaltrain.lengths` before building a mixture")
    return {r["id"] for r in json.loads(path.read_text())["over_max_length"]}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prepared", required=True)
    ap.add_argument("--tokenizer", required=True, help="model directory or hub id whose chat template is used in training")
    ap.add_argument("--revision", help="pinned revision when --tokenizer is a hub id")
    ap.add_argument("--max-length", type=int, default=4096)
    ap.add_argument("--thinking", action="store_true")
    args = ap.parse_args(argv)
    rep = profile(Path(args.prepared), args.tokenizer, args.max_length, args.thinking, revision=args.revision)
    print(json.dumps(rep["summary"], indent=2))
    print(f"{len(rep['over_max_length'])} examples exceed {args.max_length} tokens (listed in lengths.json)")


if __name__ == "__main__":
    main()
