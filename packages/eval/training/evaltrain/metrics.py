"""Task metrics and grouped bootstrap intervals.

Metrics take plain lists so a report can be recomputed from saved predictions
without the model stack. Confidence intervals resample *groups* (instruction,
source document, lecture, question group) rather than rows, because rows that share
a group are not independent.
"""
from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from collections.abc import Callable, Sequence

import numpy as np
from scipy import stats

# --- ordinal scores -------------------------------------------------------------


def _arrays(gold: Sequence[float], pred: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    g, p = np.asarray(gold, dtype=float), np.asarray(pred, dtype=float)
    if g.shape != p.shape:
        raise ValueError("gold and pred lengths differ")
    return g, p


def mae(gold, pred) -> float:
    g, p = _arrays(gold, pred)
    return float(np.mean(np.abs(g - p))) if len(g) else math.nan


def exact_agreement(gold, pred) -> float:
    g, p = _arrays(gold, pred)
    return float(np.mean(g == np.rint(p))) if len(g) else math.nan


def within_one(gold, pred) -> float:
    g, p = _arrays(gold, pred)
    return float(np.mean(np.abs(g - p) <= 1)) if len(g) else math.nan


def _corr(fn, gold, pred) -> float:
    g, p = _arrays(gold, pred)
    if len(g) < 3 or np.all(g == g[0]) or np.all(p == p[0]):
        return math.nan
    return float(fn(g, p)[0])


def pearson(gold, pred) -> float:
    return _corr(stats.pearsonr, gold, pred)


def spearman(gold, pred) -> float:
    return _corr(stats.spearmanr, gold, pred)


def kendall(gold, pred) -> float:
    return _corr(stats.kendalltau, gold, pred)


def quadratic_weighted_kappa(gold, pred, lo: int = 1, hi: int = 5) -> float:
    g = np.rint(np.asarray(gold, dtype=float)).astype(int)
    p = np.clip(np.rint(np.asarray(pred, dtype=float)), lo, hi).astype(int)
    if len(g) == 0:
        return math.nan
    k = hi - lo + 1
    observed = np.zeros((k, k))
    for a, b in zip(g - lo, p - lo, strict=True):
        observed[a, b] += 1
    weights = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)]) / (k - 1) ** 2
    expected = np.outer(observed.sum(1), observed.sum(0)) / observed.sum()
    denom = (weights * expected).sum()
    return float(1 - (weights * observed).sum() / denom) if denom else math.nan


def ordinal_report(gold, pred_int, pred_expected=None, lo: int = 1, hi: int = 5) -> dict:
    """Agreement uses the parsed integer; correlations also use the probability-weighted
    expected score when the backend returned score-token log-probabilities."""
    out = {
        "n": len(gold),
        "exact": exact_agreement(gold, pred_int),
        "within_1": within_one(gold, pred_int),
        "mae": mae(gold, pred_int),
        "pearson": pearson(gold, pred_int),
        "spearman": spearman(gold, pred_int),
        "kendall": kendall(gold, pred_int),
        "qwk": quadratic_weighted_kappa(gold, pred_int, lo, hi),
    }
    if pred_expected is not None:
        out |= {
            "mae_expected": mae(gold, pred_expected),
            "pearson_expected": pearson(gold, pred_expected),
            "spearman_expected": spearman(gold, pred_expected),
            "kendall_expected": kendall(gold, pred_expected),
        }
    return out


# --- detection --------------------------------------------------------------------


def prf(tp: float, fp: float, fn: float) -> dict:
    p = tp / (tp + fp) if tp + fp else math.nan
    r = tp / (tp + fn) if tp + fn else math.nan
    f = 2 * p * r / (p + r) if p == p and r == r and p + r else (0.0 if tp == 0 and (fp or fn) else math.nan)
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn}


def response_level_prf(gold_has: Sequence[bool], pred_has: Sequence[bool]) -> dict:
    tp = sum(g and p for g, p in zip(gold_has, pred_has, strict=True))
    fp = sum((not g) and p for g, p in zip(gold_has, pred_has, strict=True))
    fn = sum(g and (not p) for g, p in zip(gold_has, pred_has, strict=True))
    return prf(tp, fp, fn)


def _chars(spans: Sequence[tuple[int, int]]) -> set[int]:
    return {i for s, e in spans for i in range(s, e)}


def char_span_prf(gold: Sequence[Sequence[tuple[int, int]]], pred: Sequence[Sequence[tuple[int, int]]]) -> dict:
    """Micro-averaged character-overlap precision/recall/F1 over all responses."""
    tp = fp = fn = 0
    for g, p in zip(gold, pred, strict=True):
        gs, ps = _chars(g), _chars(p)
        tp += len(gs & ps)
        fp += len(ps - gs)
        fn += len(gs - ps)
    return prf(tp, fp, fn)


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Casefolded text with whitespace runs collapsed, plus a map back to original indices."""
    out, index = [], []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            prev_space = True
        else:
            out.append(ch.casefold() if len(ch.casefold()) == 1 else ch)
            prev_space = False
        index.append(i)
    return "".join(out), index


def _first_unused(haystack: str, needle: str, used: set[tuple[int, int]], to_span) -> tuple[int, int] | None:
    first = None
    start = haystack.find(needle)
    while start >= 0:
        span = to_span(start)
        if span not in used:
            return span
        first = first or span
        start = haystack.find(needle, start + 1)
    return first  # every occurrence already quoted: reuse the first rather than drop it


def locate_each(response: str, span_texts: Sequence[str]) -> list[tuple[int, int] | None]:
    """Character offsets in ``response`` for each quoted span, ``None`` where the quote
    is not in the response (quotes are reported missing, never guessed).

    Exact matches are tried first, then a whitespace/case-insensitive match. A quote
    that repeats takes the next occurrence not already matched.
    """
    norm, index = _normalized_with_map(response)
    out: list[tuple[int, int] | None] = []
    used: set[tuple[int, int]] = set()
    for raw in span_texts:
        text = raw.strip()
        span = None
        if text:
            span = _first_unused(response, text, used, lambda s, n=len(text): (s, s + n))
            if span is None:
                ntext = re.sub(r"\s+", " ", text.casefold()).strip()
                span = _first_unused(norm, ntext, used, lambda s, n=len(ntext): (index[s], index[s + n - 1] + 1))
        if span is not None:
            used.add(span)
        out.append(span)
    return out


def locate_spans(response: str, span_texts: Sequence[str]) -> tuple[list[tuple[int, int]], list[str]]:
    """``(located spans, unlocated quote texts)``; empty quotes are ignored."""
    located, unlocated = [], []
    for raw, span in zip(span_texts, locate_each(response, span_texts), strict=True):
        if span is not None:
            located.append(span)
        elif raw.strip():
            unlocated.append(raw)
    return located, unlocated


# --- grouped bootstrap -------------------------------------------------------------


def grouped_bootstrap(
    rows: Sequence[dict], metric: Callable[[Sequence[dict]], float], group_key: str = "group", n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r[group_key]].append(r)
    keys = sorted(groups)
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        sample = [r for k in (rng.choice(keys) for _ in keys) for r in groups[k]]
        v = metric(sample)
        if v == v:  # drop NaN resamples (e.g. a constant-score sample)
            vals.append(v)
    point = metric(rows)
    lo, hi = (np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)]).tolist() if vals else (math.nan, math.nan))
    return {"value": point, "ci_low": lo, "ci_high": hi, "n_rows": len(rows), "n_groups": len(keys), "n_boot": n_boot}


def paired_grouped_bootstrap(
    rows_a: Sequence[dict], rows_b: Sequence[dict], metric: Callable[[Sequence[dict]], float], group_key: str = "group", n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
) -> dict:
    """CI for ``metric(b) - metric(a)`` on the same items, resampling shared groups."""
    by_id_b = {r["id"]: r for r in rows_b}
    pairs = [(a, by_id_b[a["id"]]) for a in rows_a if a["id"] in by_id_b]
    groups: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for a, b in pairs:
        groups[a[group_key]].append((a, b))
    keys = sorted(groups)
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        sample = [p for k in (rng.choice(keys) for _ in keys) for p in groups[k]]
        d = metric([b for _, b in sample]) - metric([a for a, _ in sample])
        if d == d:
            diffs.append(d)
    point = metric([b for _, b in pairs]) - metric([a for a, _ in pairs])
    lo, hi = (np.percentile(diffs, [100 * alpha / 2, 100 * (1 - alpha / 2)]).tolist() if diffs else (math.nan, math.nan))
    return {"diff": point, "ci_low": lo, "ci_high": hi, "n_pairs": len(pairs), "n_groups": len(keys), "n_boot": n_boot}
