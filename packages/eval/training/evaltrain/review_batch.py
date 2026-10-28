"""Review an exported LMS course with the trained reviewer, as one batch job.

    python -m evaltrain.review_batch --config configs/main_27b.yaml \
        --requests review_requests.jsonl --out review_results.jsonl

The LMS writes one request per review (``apps/api/app/core/review/export.py``):

    {"id": "...", "task": "ragtruth_grounding" | "prometheus_rubric" | "oak_distractors",
     "fields": {...}, "ref": {...}}

Each request is rendered with the training templates (``evaltrain.prompts``), so the
adapter receives exactly the format it was trained and evaluated on, and runs through the
evaluation's inference path: greedy decoding, thinking off, the run's exported adapter on
its pinned base revision. Output lines are ``infer`` prediction records plus the request's
``ref``. The sidecar ``<out>.meta.json`` names the base model, revision, adapter, prompt
version and timing; the LMS import stores those with every finding.

Only public or synthetic course material may be sent to NTU batch jobs (the cluster's
open-data rule).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from evaltrain import config as C
from evaltrain import infer
from evaltrain.prompts import DISTRACTORS, GROUNDING, PROMPT_VERSION, RUBRIC, chat
from evaltrain.records import Example, read_jsonl
from evaltrain.tasks.oak import RUBRIC_TEXT as OAK_RUBRIC

REQUIRED = {
    "ragtruth_grounding": ("context", "response"),
    "prometheus_rubric": ("instruction", "response", "reference", "criteria", "score1", "score2", "score3", "score4", "score5"),
    "oak_distractors": ("question", "answer", "distractors"),
}


def render(req: dict) -> Example:
    task, fields = req.get("task"), req.get("fields") or {}
    if task not in REQUIRED:
        raise ValueError(f"request {req.get('id')}: unknown task {task!r}")
    missing = [k for k in REQUIRED[task] if not fields.get(k)]
    if missing:
        raise ValueError(f"request {req['id']}: missing fields {missing}")
    if task == "ragtruth_grounding":
        user = GROUNDING.format(context=fields["context"], response=fields["response"])
    elif task == "prometheus_rubric":
        user = RUBRIC.format(**{k: fields[k] for k in REQUIRED[task]})
    else:
        distractors = "\n".join(f"- {d.strip()}" for d in fields["distractors"])
        user = DISTRACTORS.format(rubric=OAK_RUBRIC, question=fields["question"].strip(), answer=fields["answer"].strip(), distractors=distractors)
    return Example(id=req["id"], task=task, dataset="lms", split="review", group=req["id"], messages=chat(user), target=None, gold={}, meta={"ref": req.get("ref")})


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="experiment config: its model, revision and run adapter are used")
    ap.add_argument("--requests", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-adapter", action="store_true", help="review with the untrained base model instead")
    ap.add_argument("--backend", choices=["vllm", "hf"], default="vllm")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-model-len", type=int, default=8192)
    args = ap.parse_args(argv)

    cfg = C.load(args.config)
    requests = list(read_jsonl(args.requests))
    ids = [r["id"] for r in requests]
    if len(ids) != len(set(ids)):
        raise SystemExit("request ids must be unique")
    examples = [render(r) for r in requests]
    refs = {r["id"]: r.get("ref") for r in requests}

    model = cfg["model"]
    adapter = None if args.no_adapter else str(C.run_dir(cfg) / "adapter")
    if adapter and not Path(adapter, "adapter_config.json").exists():
        raise SystemExit(f"no exported adapter at {adapter}")
    lora_rank = cfg.get("lora", {}).get("rank", 16)
    if args.backend == "vllm":
        backend = infer.VLLMBackend(model["id"], model.get("revision"), adapter, args.max_model_len, False, infer.Sampling(), lora_rank, False, 0.90)
    else:
        backend = infer.HFBackend(model.get("path") or model["id"], model.get("revision"), adapter, False, False)

    out = Path(args.out)
    raw = out.with_suffix(".predictions.jsonl")
    stats = infer.run(examples, raw, backend, batch_size=args.batch_size if args.backend == "vllm" else 1, thinking=False, extra_think_tokens=0, image_root=None, deadline=None)
    rows = [dict(p, ref=refs.get(p["id"])) for p in read_jsonl(raw)]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    serving = json.loads(Path(adapter, "serving.json").read_text()) if adapter else {}
    meta = {
        "reviewer": {
            "base_model": model["id"], "base_revision": model.get("revision"), "adapter": cfg["run_id"] if adapter else None,
            "adapter_checkpoint": serving.get("checkpoint"), "training_hash": serving.get("training_hash"),
            "prompt_version": PROMPT_VERSION, "thinking": False, "sampling": {"temperature": 0.0},
        },
        "requests": len(requests), "valid": sum(r["valid"] for r in rows), "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "inference": stats,  # seconds here exclude model loading
    }
    out.with_suffix(out.suffix + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"requests": meta["requests"], "valid": meta["valid"], "inference_seconds": round(stats["seconds"], 1)}))


if __name__ == "__main__":
    main()
