#!/usr/bin/env python3
"""Model bundle manifest: record and verify the exact model files a deployment serves.

    python scripts/models.py lock --base Qwen/Qwen3.5-9B@<revision> --adapter reviewer-pilot-9b-v1
    python scripts/models.py verify            # full SHA-256 check
    python scripts/models.py verify --quick    # presence and sizes only

The bundle lives in data/models (git-ignored): base models in the Hugging Face cache
under data/models/hf, where the gpu-profile inference container reads them offline,
and custom LoRA adapters under data/models/adapters/<dir>. `lock` hashes every file and
writes infra/models.lock.json, which is committed with the release. `verify` runs on
the serving machine and fails on any missing, changed or unexpected file, on an adapter
trained on a base model that is not locked, and on .env serving settings
(VLLM_MODEL, VLLM_REVISION, VLLM_LORA_MODULES, REVIEWER_MODEL) that disagree with the
lock. Standard library only, like the other host scripts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def snapshot_dir(models: Path, model_id: str, revision: str) -> Path:
    return models / "hf" / "hub" / f"models--{model_id.replace('/', '--')}" / "snapshots" / revision


def sha256(path: Path, chunk: int = 1 << 24) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def describe(folder: Path, quick: bool = False) -> dict[str, dict]:
    """Every file under ``folder`` (following the HF cache's symlinks) with size and hash."""
    files = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if path.is_file() and ".cache" not in rel.parts:
            files[rel.as_posix()] = {"bytes": path.stat().st_size} | ({} if quick else {"sha256": sha256(path)})
    return files


def compare(folder: Path, expected: dict[str, dict], label: str, quick: bool) -> list[str]:
    if not folder.is_dir():
        return [f"{label}: {folder} is missing"]
    actual = describe(folder, quick=quick)
    problems = [f"{label}: missing {name}" for name in sorted(set(expected) - set(actual))]
    problems += [f"{label}: unexpected file {name} (not in the lock)" for name in sorted(set(actual) - set(expected))]
    for name in sorted(set(expected) & set(actual)):
        want, got = expected[name], actual[name]
        if want["bytes"] != got["bytes"]:
            problems.append(f"{label}: {name} is {got['bytes']} bytes, locked {want['bytes']}")
        elif not quick and want["sha256"] != got["sha256"]:
            problems.append(f"{label}: {name} checksum differs from the lock")
    return problems


def read_env(path: Path) -> dict[str, str]:
    env = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def check_env(env: dict[str, str], record: dict) -> list[str]:
    """Serving settings must point at what the lock contains."""
    if "gpu" not in env.get("COMPOSE_PROFILES", ""):
        return []
    problems = []
    bases = {b["id"]: b["revision"] for b in record["base_models"]}
    adapters = {a["dir"]: a for a in record["adapters"]}
    base = env.get("VLLM_BASE_ID") or env.get("VLLM_MODEL", "")
    if base not in bases:
        problems.append(f".env: VLLM_MODEL/VLLM_BASE_ID {base!r} is not a locked base model ({', '.join(bases) or 'none'})")
    elif env.get("VLLM_REVISION") != bases[base]:
        problems.append(f".env: set VLLM_REVISION={bases[base]} (the locked revision of {base})")
    served = {}
    for pair in env.get("VLLM_LORA_MODULES", "").split():
        name, _, folder = pair.partition("=")
        served[name] = folder
        if folder not in adapters:
            problems.append(f".env: VLLM_LORA_MODULES serves {folder!r}, which is not a locked adapter")
        elif adapters[folder]["base_model"] != base:
            problems.append(f".env: adapter {folder} was trained on {adapters[folder]['base_model']}, not {base}")
    if env.get("REVIEWER_ENABLED", "false").lower() == "true" and env.get("REVIEWER_MODEL") not in served:
        problems.append(f".env: REVIEWER_MODEL {env.get('REVIEWER_MODEL')!r} is not one of the served adapters ({', '.join(served) or 'none'})")
    return problems


def cmd_lock(args) -> int:
    models = Path(args.models_dir)
    bases = []
    for spec in args.base:
        model_id, _, revision = spec.partition("@")
        if not revision:
            sys.exit(f"--base {spec}: give ID@REVISION so the lock pins an immutable snapshot")
        folder = snapshot_dir(models, model_id, revision)
        if not folder.is_dir():
            sys.exit(f"{folder} not found: download {model_id} at {revision} into {models / 'hf'} first")
        print(f"hashing {model_id}@{revision[:12]} ...", file=sys.stderr)
        bases.append({"id": model_id, "revision": revision, "files": describe(folder)})
    adapters = []
    locked = {(b["id"], b["revision"]) for b in bases}
    for name in args.adapter:
        folder = models / "adapters" / name
        serving_path = folder / "serving.json"
        if not serving_path.is_file():
            sys.exit(f"{serving_path} not found (promote the adapter with `python -m evaltrain.promote`)")
        serving = json.loads(serving_path.read_text(encoding="utf-8"))
        base = (serving.get("base_model"), serving.get("base_revision"))
        if base not in locked:
            sys.exit(f"adapter {name} was trained on {base[0]}@{base[1]}: lock that base too (--base {base[0]}@{base[1]})")
        print(f"hashing adapter {name} ...", file=sys.stderr)
        adapters.append({"dir": name, "base_model": base[0], "base_revision": base[1], "files": describe(folder)})
    record = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "base_models": bases, "adapters": adapters}
    lock_path = Path(args.lock)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    total = sum(f["bytes"] for entry in [*bases, *adapters] for f in entry["files"].values())
    print(f"wrote {lock_path}: {len(bases)} base model(s), {len(adapters)} adapter(s), {total / 1e9:.1f} GB")
    return 0


def cmd_verify(args) -> int:
    lock_path = Path(args.lock)
    if not lock_path.is_file():
        print(f"{lock_path} not found: assemble the bundle, then run `make models-lock`", file=sys.stderr)
        return 2
    record = json.loads(lock_path.read_text(encoding="utf-8"))
    models = Path(args.models_dir)
    problems = []
    for b in record["base_models"]:
        problems += compare(snapshot_dir(models, b["id"], b["revision"]), b["files"], f"{b['id']}@{b['revision'][:12]}", args.quick)
    for a in record["adapters"]:
        problems += compare(models / "adapters" / a["dir"], a["files"], f"adapter {a['dir']}", args.quick)
    problems += check_env(read_env(Path(args.env)), record)
    if problems:
        print("model bundle does NOT match the lock:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    mode = "sizes" if args.quick else "SHA-256"
    print(f"model bundle matches {lock_path} ({mode}): {len(record['base_models'])} base model(s), {len(record['adapters'])} adapter(s)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models-dir", default=str(ROOT / "data" / "models"))
    ap.add_argument("--lock", default=str(ROOT / "infra" / "models.lock.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    lock = sub.add_parser("lock", help="hash the bundle and write the lock file")
    lock.add_argument("--base", action="append", default=[], metavar="ID@REVISION", help="base model snapshot in data/models/hf")
    lock.add_argument("--adapter", action="append", default=[], metavar="DIR", help="adapter directory under data/models/adapters")
    verify = sub.add_parser("verify", help="check the bundle and .env against the lock file")
    verify.add_argument("--quick", action="store_true", help="compare presence and sizes only")
    verify.add_argument("--env", default=str(ROOT / ".env"))
    args = ap.parse_args(argv)
    return cmd_lock(args) if args.cmd == "lock" else cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())
