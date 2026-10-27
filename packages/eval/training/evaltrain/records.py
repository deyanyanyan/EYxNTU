"""Prepared review examples and the JSONL files that carry them between stages.

One ``Example`` is one review request with its published label. ``messages`` holds
only the system and user turns; ``target`` is the assistant turn used for training
(a serialized JSON review built mechanically from the dataset's own labels), and
``gold`` holds the raw labels the scorer compares predictions against.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Example:
    id: str
    task: str
    dataset: str
    split: str
    group: str
    messages: list[dict]
    target: str | None
    gold: dict
    images: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Example:
        return cls(**d)


def write_jsonl(path: str | Path, rows: Iterable[dict | Example]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r.to_dict() if isinstance(r, Example) else r, ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


def read_jsonl(path: str | Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def read_examples(path: str | Path) -> list[Example]:
    return [Example.from_dict(d) for d in read_jsonl(path)]


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump_target(obj: dict) -> str:
    """Canonical serialization of a training target: key order as given, no ASCII escaping."""
    return json.dumps(obj, ensure_ascii=False)
