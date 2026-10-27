"""Experiment configuration: YAML with ``${ENV}`` expansion and a training hash.

``training_hash`` covers everything that defines the optimisation trajectory (model
revision, template, data mixture, lengths, LoRA, schedule, seed). It is written at the
first launch and checked on every resume, so a chained job cannot silently continue a
run under a different dataset or schedule. Walltime and evaluation settings are
excluded: they may change between jobs without changing what is being trained.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import yaml

TRAINING_KEYS = ("seed", "model", "data", "lora", "train")
_UNRESOLVED = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")


def _expand(value):
    if isinstance(value, str):
        out = os.path.expandvars(value)
        if _UNRESOLVED.search(out):
            raise ValueError(f"unresolved environment variable in config value {value!r}")
        return out
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load(path: str | Path) -> dict:
    cfg = _expand(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    for key in ("run_id", "model", "data", "train"):
        if key not in cfg:
            raise ValueError(f"config {path} is missing '{key}'")
    cfg["_path"] = str(path)
    return cfg


def training_hash(cfg: dict) -> str:
    payload = {k: cfg.get(k) for k in TRAINING_KEYS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def root() -> Path:
    value = os.environ.get("EVALTRAIN_ROOT")
    if not value:
        raise OSError("EVALTRAIN_ROOT is not set (source pbs/env.sh on the cluster, or export it locally)")
    return Path(value)


def run_dir(cfg: dict) -> Path:
    return root() / "runs" / cfg["run_id"]


def prepared_dir(cfg: dict) -> Path:
    return Path(cfg["data"].get("prepared_dir") or root() / "prepared" / cfg["data"]["version"])
