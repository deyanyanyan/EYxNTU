"""Deterministic grouped splits and leakage audits.

A split assignment is a pure function of ``(salt, group key)``: the key is hashed
with SHA-256 into a bucket in [0, 1) and the bucket is compared with cumulative
split fractions. Anyone can recompute the split from the code and the raw data, and
adding rows never moves an existing group to another partition.

Groups that must not straddle partitions (an instruction and its five graded
responses, a RAGTruth source and its six generated responses, ...) are merged with a
union-find over every grouping key, so two items sharing *any* key end up together.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def text_key(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:20]


def bucket(key: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}\x00{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def assign(key: str, salt: str, fractions: dict[str, float]) -> str:
    """Map a group key onto one of ``fractions`` (insertion order, summing to 1)."""
    if abs(sum(fractions.values()) - 1.0) > 1e-9:
        raise ValueError(f"split fractions must sum to 1: {fractions}")
    b, acc, name = bucket(key, salt), 0.0, ""
    for name, frac in fractions.items():
        acc += frac
        if b < acc:
            return name
    return name


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # keep the lexicographically smallest root so group ids are order-independent
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def connected_groups(items: Iterable[tuple[str, Iterable[str]]]) -> dict[str, str]:
    """``items`` are ``(item_id, keys)``; returns item_id -> group id (smallest member key)."""
    uf = UnionFind()
    first_key: dict[str, str] = {}
    for item_id, keys in items:
        keys = list(keys)
        if not keys:
            raise ValueError(f"item {item_id} has no grouping keys")
        first_key[item_id] = keys[0]
        for k in keys[1:]:
            uf.union(keys[0], k)
    return {item_id: uf.find(k) for item_id, k in first_key.items()}


def audit_leakage(records: list[dict], key_fns: dict[str, Callable[[dict], Iterable[str]]], split_field: str = "split") -> dict:
    """For each named key function, list key values that occur in more than one split.

    Returns ``{"counts": {...}, "violations": {name: [(key, [splits...]), ...]}}``;
    callers fail the preparation step when any violation list is non-empty.
    """
    counts = Counter(r[split_field] for r in records)
    violations: dict[str, list] = {}
    for name, fn in key_fns.items():
        seen: dict[str, set[str]] = defaultdict(set)
        for r in records:
            for k in fn(r):
                seen[k].add(r[split_field])
        bad = sorted((k, sorted(s)) for k, s in seen.items() if len(s) > 1)
        violations[name] = bad[:50]
        if bad:
            violations[name + "_total"] = len(bad)
    return {"counts": dict(sorted(counts.items())), "violations": violations}


def has_violations(audit: dict) -> bool:
    return any(v for k, v in audit["violations"].items() if not k.endswith("_total"))
