"""Task registry.

Each public dataset becomes one review task with its own prompt, label semantics,
parser and metrics. Tasks keep their original scales and are never merged into a
single quality score.

A task module provides:

* ``build(raw_dir, cfg) -> (examples, record)``: deterministic conversion of the raw
  files into ``Example`` rows with split assignments, plus a provenance/audit record;
* ``parse(obj) -> dict``: validation of the model's JSON object (raises ``ValueError``);
* ``point_metrics(rows) -> dict`` and ``ci_metrics``: scalar metrics over joined rows,
  the latter bootstrapped by group and used for base-versus-adapter comparisons.

A joined row is ``{"id", "group", "gold", "pred", "valid", "strict", "dist"}``; ``pred``
is ``None`` when the output could not be parsed.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from evaltrain.records import Example


@dataclass(frozen=True)
class Task:
    name: str
    dataset: str
    build: Callable[[Path, dict], tuple[list[Example], dict]]
    parse: Callable[[dict], dict]
    point_metrics: Callable[[list[dict]], dict]
    ci_metrics: dict[str, Callable[[list[dict]], float]] = field(default_factory=dict)
    score_keys: tuple[str, ...] = ()
    max_new_tokens: int = 512
    multimodal: bool = False


def registry() -> dict[str, Task]:
    from evaltrain.tasks import leceval, oak, prometheus, ragtruth

    tasks = [prometheus.TASK, ragtruth.TASK, oak.TASK, leceval.TASK]
    return {t.name: t for t in tasks}


def get(name: str) -> Task:
    tasks = registry()
    if name not in tasks:
        raise KeyError(f"unknown task {name!r}; known: {sorted(tasks)}")
    return tasks[name]
