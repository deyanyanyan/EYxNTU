"""Inference plus scoring for one arm of an experiment.

    python -m evaltrain.run_eval --config configs/pilot_9b.yaml --arm base
    python -m evaltrain.run_eval --config configs/pilot_9b.yaml --arm adapter
    python -m evaltrain.run_eval --config configs/pilot_9b.yaml --arm base-thinking

Arms run on identical examples and prompts; only the model side differs:
  base           the pinned post-trained checkpoint, thinking off
  base-thinking  the same checkpoint with the template's thinking mode on (stronger,
                 slower baseline: an adapter should be compared with it as well)
  adapter        the run's exported serving adapter on the same base revision
  merged         the adapter merged into the base weights (<run>/merged), the fallback if
                 vLLM's LoRA path misbehaves; create it with
                 swift export --adapters <run>/adapter --merge_lora true --output_dir <run>/merged

The development split is the default. The test split requires ``--final``: it is
meant to be scored once, for the configurations already selected on dev, and each
use is appended to ``test_access.jsonl`` in the run directory.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from evaltrain import config as C
from evaltrain import evaluate, infer
from evaltrain.records import read_examples, read_jsonl, write_jsonl


def subsample_by_group(exs: list, limit: int) -> list:
    """Deterministic subsample that keeps every group represented.

    Taking whole groups would evaluate Prometheus dev on about six rubrics (42 groups of
    ~100 rows); instead each group contributes up to ``ceil(limit / groups)`` rows, chosen
    by hash order, so grouped bootstrap intervals still resample all groups.
    """
    import math

    from evaltrain.splits import bucket

    by_group: dict[str, list] = {}
    for e in exs:
        by_group.setdefault(e.group, []).append(e)
    cap = math.ceil(limit / len(by_group))
    keep = {e.id for g in by_group.values() for e in sorted(g, key=lambda e: bucket(e.id, "eval-subsample"))[:cap]}
    return [e for e in exs if e.id in keep]


def eval_examples(cfg: dict, split: str, out_dir: Path, limit: int | None) -> Path:
    """Per-task subsample; a smaller limit selects a subset of a larger limit's items,
    so the thinking arm's items are always among the other arms' items."""
    ev = cfg.get("eval", {})
    prepared = C.prepared_dir(cfg)
    rows = []
    for task in ev.get("tasks", list(cfg["data"]["mixture"])):
        path = prepared / f"{task}.{split}.jsonl"
        exs = read_examples(path)
        if limit and len(exs) > limit:
            exs = subsample_by_group(exs, limit)
        rows += exs
    path = out_dir / "examples.jsonl"
    write_jsonl(path, rows)
    return path


def adapter_effect(base_preds: Path, adapter_preds: Path) -> dict:
    """Share of items where the adapter's raw output equals the base model's.

    A LoRA adapter that silently fails to attach (for example vLLM serving an adapter
    whose module names do not match the loaded model class) reproduces the base outputs
    exactly; a share near 1.0 means the adapter run must not be reported.
    """
    if not base_preds.exists():
        return {"checked": False, "reason": "no base predictions for this split yet"}
    base = {r["id"]: r["raw"] for r in read_jsonl(base_preds)}
    pairs = [(base[r["id"]], r["raw"]) for r in read_jsonl(adapter_preds) if r["id"] in base]
    same = sum(a == b for a, b in pairs) / len(pairs) if pairs else float("nan")
    result = {"checked": True, "compared": len(pairs), "identical_share": same}
    if pairs and same > 0.95:
        result["warning"] = "adapter outputs match the base model on >95% of items: the adapter is probably not applied"
        print(f"WARNING: {result['warning']}")
    return result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--arm", choices=["base", "base-thinking", "adapter", "merged"], default="base")
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--final", action="store_true", help="required for --split test")
    ap.add_argument("--adapter", help="override the adapter path (default: <run>/adapter)")
    ap.add_argument("--backend", choices=["vllm", "hf", "openai"], default="vllm")
    ap.add_argument("--deadline-epoch", type=float)
    args = ap.parse_args(argv)

    cfg = C.load(args.config)
    if args.split == "test" and not args.final:
        raise SystemExit("the test split is scored once, after selection on dev: pass --final to confirm")
    run = C.run_dir(cfg)
    out_dir = run / "eval" / f"{args.arm}-{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.split == "test":
        with (run / "test_access.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"arm": args.arm, "at_epoch": time.time(), "config": cfg["_path"]}) + "\n")

    ev = cfg.get("eval", {})
    thinking = args.arm == "base-thinking"
    examples = out_dir / "examples.jsonl"
    if not examples.exists():
        # Thinking replies run to thousands of tokens: a smaller, nested subsample keeps the arm
        # affordable. The test split is scored once and in full (eval.test_limit_per_task unset).
        if thinking:
            limit = ev.get("thinking_limit_per_task", 200)
        elif args.split == "test":
            limit = ev.get("test_limit_per_task")
        else:
            limit = ev.get("limit_per_task")
        examples = eval_examples(cfg, args.split, out_dir, limit)

    model = dict(cfg["model"])
    adapter = None
    if args.arm == "adapter":
        adapter = args.adapter or str(run / "adapter")
        if not Path(adapter).is_dir():
            raise SystemExit(f"adapter not found: {adapter} (training exports it on completion; or train.py --export)")
    if args.arm == "merged":
        merged = run / "merged"
        if not (merged / "config.json").exists():
            raise SystemExit(f"merged model not found: {merged} (see the 'merged' arm in this module's help)")
        model = {"path": str(merged)}
    preds = out_dir / "predictions.jsonl"
    infer.main([
        "--examples", str(examples), "--out", str(preds), "--backend", args.backend,
        "--model", model.get("path") or model["id"], *(["--revision", model["revision"]] if model.get("revision") and not model.get("path") else []),
        *(["--adapter", adapter] if adapter else []),
        # thinking sampling from the Qwen3.5/3.8 model cards and Qwen3.8's generation_config
        *(["--thinking", "--temperature", "1.0", "--top-p", "0.95", "--top-k", "20", "--seed", str(cfg["seed"])] if thinking else []),
        # A 4,096-token thinking budget truncated 26-75% of Qwen3.5-9B's replies mid-reasoning
        # (27 Oct 2026; RAGTruth averaged 4,691 output tokens), so the arm measured the budget,
        # not the model. 16K thinking tokens on prompts of up to ~3K need a 32K context.
        *(["--extra-think-tokens", str(ev.get("think_tokens", 16384))] if thinking else []),
        "--max-model-len", str(ev.get("max_model_len_thinking", 32768) if thinking else ev.get("max_model_len", 8192)),
        "--batch-size", str(ev.get("batch_size", 64)),
        "--lora-rank", str(cfg.get("lora", {}).get("rank", 32)),
        *(["--image-root", str(C.prepared_dir(cfg))] if ev.get("multimodal") else []),
        *(["--deadline-epoch", str(args.deadline_epoch)] if args.deadline_epoch else []),
    ])
    report = evaluate.evaluate(examples, preds)
    if args.arm in ("adapter", "merged"):
        report["adapter_effect"] = adapter_effect(run / "eval" / f"base-{args.split}" / "predictions.jsonl", preds)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(evaluate.to_markdown(report), encoding="utf-8")
    print(evaluate.to_markdown(report))


if __name__ == "__main__":
    main()
