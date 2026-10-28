"""Launch or resume one experiment's LoRA training within a PBS walltime budget.

    python -m evaltrain.train --config configs/pilot_9b.yaml --job-start-epoch $START --walltime-seconds 14400
    python -m evaltrain.train --config configs/pilot_9b.yaml --dry-run    # print the MS-SWIFT command only
    python -m evaltrain.train --config configs/pilot_9b.yaml --export     # export the serving adapter

Run directory ``$EVALTRAIN_ROOT/runs/<run_id>/``:

  run.json             first-launch record: config, training hash, Git revision, data and
                       prompt hashes, package versions, GPU
  data/train.jsonl     the materialised mixture (MS-SWIFT messages format), mixture.json
  train/checkpoint-N/  complete resumable checkpoints: adapter, optimizer, scheduler, RNG,
                       trainer state and CHECKPOINT_COMPLETE.json
  train/job_status.json, train/trainable_params.json, train/TRAINING_COMPLETE.json
  jobs.jsonl           one line per job: PBS id, steps covered, stop reason, timings
  adapter/             exported serving adapter plus serving.json

Every job after the first verifies the training hash and the mixture checksum, then
resumes from the newest checkpoint carrying the completion marker. The schedule
(epochs, warm-up, learning rate) is fixed by the config for the whole experiment;
the walltime callback limits each job instead of each job resetting ``max_steps``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from evaltrain import config as C
from evaltrain.callbacks import (
    ENV_EXPECTED_ROWS,
    ENV_STATUS_DIR,
    STATUS_FILE,
    TRAINING_DONE_MARKER,
    WalltimeBudget,
    latest_complete_checkpoint,
)
from evaltrain.lengths import overlength_ids
from evaltrain.mixture import build as build_mixture
from evaltrain.prompts import PROMPT_VERSION
from evaltrain.records import sha256_file

PLUGIN = Path(__file__).with_name("swift_plugin.py")
RENDER_OK_MARKER = "RENDER_CHECK_OK.json"


def _git_revision() -> str | None:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=Path(__file__).parents[1], capture_output=True, text=True).stdout.strip()
        return rev + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def _code_sha256() -> str:
    """Hash of the package, configs, job scripts and pins, for copies that are not Git checkouts."""
    import hashlib

    base = Path(__file__).parents[1]
    h = hashlib.sha256()
    for pattern in ("evaltrain/**/*.py", "configs/*.yaml", "pbs/*.pbs", "pbs/*.sh", "requirements/*.txt"):
        for path in sorted(base.glob(pattern)):
            if path.name == "env.sh":
                continue
            h.update(path.relative_to(base).as_posix().encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()[:16]


def _environment() -> dict:
    import importlib.metadata as md

    env = {"python": sys.version.split()[0]}
    for pkg in ("torch", "transformers", "peft", "trl", "datasets", "ms_swift", "vllm", "flash-linear-attention", "causal-conv1d", "flash-attn"):
        try:
            env[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            pass
    try:
        env["gpu"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        env["gpu"] = None
    return env


def swift_args(cfg: dict, run: Path, mixture_path: Path, resume: Path | None) -> list[str]:
    m, lo, tr, d = cfg["model"], cfg.get("lora", {}), cfg["train"], cfg["data"]
    a = {
        "model": m.get("path") or m["id"],
        "use_hf": "true",  # MS-SWIFT defaults to the ModelScope hub
        "template": m["template"],
        "torch_dtype": "bfloat16",
        "tuner_type": "lora",
        "lora_rank": lo.get("rank", 16),
        "lora_alpha": lo.get("alpha", 32),
        "lora_dropout": lo.get("dropout", 0.05),
        "target_modules": lo.get("target_modules", "all-linear"),  # LLM only on multimodal models
        "freeze_vit": "true",
        "freeze_aligner": "true",
        "dataset": str(mixture_path),
        "max_length": d["max_length"],
        "lazy_tokenize": "false",  # eager encoding: dataset size is known before step 1
        "strict": "true",  # raise instead of silently dropping or substituting samples
        "dataset_shuffle": "true",
        "data_seed": cfg["seed"],
        "seed": cfg["seed"],
        "split_dataset_ratio": 0,  # development data comes from our own grouped split
        "add_non_thinking_prefix": "true",  # empty think block, masked by +ignore_empty_think
        "num_train_epochs": tr["epochs"],
        "per_device_train_batch_size": tr.get("per_device_batch_size", 1),
        "gradient_accumulation_steps": tr.get("grad_accum", 16),
        "learning_rate": tr["learning_rate"],
        "lr_scheduler_type": tr.get("lr_scheduler", "cosine"),
        "warmup_ratio": tr.get("warmup_ratio", 0.05),
        "weight_decay": tr.get("weight_decay", 0.0),
        "max_grad_norm": tr.get("max_grad_norm", 1.0),
        "gradient_checkpointing": "true",
        "attn_impl": tr.get("attn_impl", "sdpa"),
        "packing": str(tr.get("packing", False)).lower(),
        "output_dir": str(run / "train"),
        "add_version": "false",  # one stable directory across PBS jobs
        "save_strategy": "steps",
        "save_steps": 10**9,  # periodic saves come from the walltime callback; the trainer still saves at the end
        "save_total_limit": tr.get("save_total_limit", 3),
        "save_only_model": "false",
        "eval_strategy": "no",
        "logging_steps": tr.get("logging_steps", 5),
        "report_to": "tensorboard",
        "dataloader_num_workers": tr.get("dataloader_num_workers", 4),
        "external_plugins": str(PLUGIN),
        "callbacks": "evaltrain_walltime",
    }
    if m.get("revision") and not m.get("path"):
        a["model_revision"] = m["revision"]
    if resume:
        a["resume_from_checkpoint"] = str(resume)
    for k, v in tr.get("extra_swift_args", {}).items():
        a[k] = v
    out: list[str] = []
    for k, v in a.items():
        out += [f"--{k}", *(v if isinstance(v, list) else [str(v)])]
    return out


def first_launch(cfg: dict, run: Path) -> dict:
    prepared = C.prepared_dir(cfg)
    data_dir = run / "data"
    mix = build_mixture(prepared, cfg["data"]["mixture"], data_dir / "train.jsonl", salt=cfg["data"].get("mixture_salt", "evaltrain-mixture-v1"),
                        seed=cfg["seed"], overlength_ids=overlength_ids(prepared))
    record = {
        "run_id": cfg["run_id"], "created_at_epoch": time.time(), "training_hash": C.training_hash(cfg), "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "config_path": cfg["_path"], "git_revision": _git_revision(), "code_sha256": _code_sha256(), "prompt_version": PROMPT_VERSION, "mixture": mix,
        "data_record_sha256": sha256_file(prepared / "data_record.json") if (prepared / "data_record.json").exists() else None,
        "lengths_sha256": sha256_file(prepared / "lengths.json"), "environment": _environment(),
    }
    (run / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def verify_resume(cfg: dict, run: Path) -> dict:
    record = json.loads((run / "run.json").read_text())
    now_hash = C.training_hash(cfg)
    if record["training_hash"] != now_hash:
        raise SystemExit(f"training config changed since the run started ({record['training_hash']} -> {now_hash}); start a new run_id instead")
    mixture = run / "data" / "train.jsonl"
    if sha256_file(mixture) != record["mixture"]["file_sha256"]:
        raise SystemExit(f"{mixture} changed since the run started; refusing to resume on different data")
    if record["prompt_version"] != PROMPT_VERSION:
        raise SystemExit(f"prompt templates changed ({record['prompt_version']} -> {PROMPT_VERSION}); start a new run_id")
    return record


def export_adapter(cfg: dict, run: Path) -> Path:
    if not (run / "train" / TRAINING_DONE_MARKER).exists():
        print("WARNING: exporting before TRAINING_COMPLETE: this adapter is an intermediate checkpoint")
    ckpt = latest_complete_checkpoint(run / "train")
    if ckpt is None:
        raise SystemExit("no complete checkpoint to export")
    dest = run / "adapter"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in ("adapter_model.safetensors", "adapter_config.json", "additional_config.json", "args.json"):
        if (ckpt / name).exists():
            shutil.copy2(ckpt / name, dest / name)
    record = json.loads((run / "run.json").read_text())
    serving = {
        "base_model": cfg["model"]["id"], "base_revision": cfg["model"].get("revision"), "template": cfg["model"]["template"], "enable_thinking": False,
        "prompt_version": PROMPT_VERSION, "training_hash": record["training_hash"], "checkpoint": ckpt.name, "lora_rank": cfg.get("lora", {}).get("rank", 16),
        "sampling": {"temperature": 0.0}, "contract": "see packages/eval/training/README.md#batch-inference-contract",
    }
    (dest / "serving.json").write_text(json.dumps(serving, indent=2), encoding="utf-8")
    print(f"exported {ckpt} -> {dest}")
    return dest


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--job-start-epoch", type=float, help="PBS job start (date +%%s); defaults to now")
    ap.add_argument("--walltime-seconds", type=float, default=4 * 3600)
    ap.add_argument("--stop-after-steps", type=int, help="save and stop after N optimizer steps in this job (stop/resume test)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args(argv)

    cfg = C.load(args.config)
    run = C.run_dir(cfg)
    if args.export:
        export_adapter(cfg, run)
        return
    if (run / "train" / TRAINING_DONE_MARKER).exists():
        print(f"{cfg['run_id']}: training already complete; nothing to do")
        return
    run.mkdir(parents=True, exist_ok=True)
    record = verify_resume(cfg, run) if (run / "run.json").exists() else first_launch(cfg, run)
    resume = latest_complete_checkpoint(run / "train")
    if not args.dry_run and not (run / RENDER_OK_MARKER).exists():
        # Until it has passed once: prove MS-SWIFT's training encoding matches the inference template.
        render_check = subprocess.run([sys.executable, "-m", "evaltrain.swift_render", "--config", args.config, "--n", "3"])
        if render_check.returncode != 0:
            raise SystemExit("render check failed; see swift_render.md in the run directory")

    wt = cfg.get("walltime", {})
    budget = WalltimeBudget.from_job(args.job_start_epoch or time.time(), args.walltime_seconds, reserve_s=60 * wt.get("reserve_minutes", 20),
                                     save_every_s=60 * wt.get("save_every_minutes", 12), stop_after_steps=args.stop_after_steps)
    cmd = [sys.executable, "-m", "swift.cli.sft", *swift_args(cfg, run, run / "data" / "train.jsonl", resume)]
    env = os.environ | budget.to_env() | {ENV_STATUS_DIR: str(run / "train"), ENV_EXPECTED_ROWS: str(record["mixture"]["rows"]), "USE_HF": "1",
                                          "PYTORCH_CUDA_ALLOC_CONF": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")}
    print(f"[evaltrain] run={cfg['run_id']} resume={resume} deadline_in={budget.deadline - time.time():.0f}s")
    print("[evaltrain] " + " ".join(cmd))
    if args.dry_run:
        return

    started = time.time()
    rc = subprocess.run(cmd, env=env).returncode
    status_path = run / "train" / STATUS_FILE
    status = json.loads(status_path.read_text()) if status_path.exists() and status_path.stat().st_mtime >= started else {"status": "no-status"}
    job = {"job_id": os.environ.get("PBS_JOBID"), "started_at_epoch": started, "seconds": time.time() - started, "returncode": rc, "resumed_from": str(resume) if resume else None,
           **{k: status.get(k) for k in ("status", "stop_reason", "first_global_step", "global_step", "max_steps", "step_seconds_ema")}, "saves": status.get("saves")}
    with (run / "jobs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(job) + "\n")
    print(f"[evaltrain] job finished: {json.dumps({k: job[k] for k in ('returncode', 'status', 'stop_reason', 'first_global_step', 'global_step', 'max_steps')})}")
    if rc != 0 or job["status"] not in ("stopped", "completed"):
        raise SystemExit(rc or 1)
    if job["status"] == "completed":
        export_adapter(cfg, run)


if __name__ == "__main__":
    main()
