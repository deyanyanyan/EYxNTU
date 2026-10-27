"""Extracting the JSON review object, and score distributions, from model output.

``strict`` validity means the whole answer (after any thinking block) is one JSON
object; ``lenient`` validity means one could be recovered from surrounding text or a
code fence. Both rates are reported, because the LMS integration should not silently
depend on the lenient path.

For 1-5 scores, the probability-weighted expected score is computed from the
log-probabilities at the position where the model wrote the score digit. Qwen
tokenizers split numbers into single digits, so each score is one token.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Sequence

THINK_END = "</think>"
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def strip_thinking(text: str) -> str:
    return text.rsplit(THINK_END, 1)[1] if THINK_END in text else text


def extract_json(text: str) -> tuple[dict | None, bool, str | None]:
    """Returns ``(object, strict, error)``."""
    body = strip_thinking(text).strip()
    try:
        obj = json.loads(body)
        if isinstance(obj, dict):
            return obj, True, None
    except json.JSONDecodeError:
        pass
    m = _FENCE.match(body)
    candidates = [m.group(1)] if m else []
    candidates.append(body)
    dec = json.JSONDecoder()
    for cand in candidates:
        for i, ch in enumerate(cand):
            if ch != "{":
                continue
            try:
                obj, _ = dec.raw_decode(cand[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj, False, None
    return None, False, "no JSON object found"


def score_distributions(
    pieces: Sequence[str], top_logprobs: Sequence[Iterable[tuple[str, float]]], keys: Sequence[str], lo: int = 1, hi: int = 5
) -> dict[str, dict[str, float]]:
    """``pieces[i]`` is the decoded text of generated token i and ``top_logprobs[i]`` lists
    ``(candidate token text, log-probability)`` at that position (several token ids can
    decode to the same text, so this is a list, not a dict). Returns, for each score key
    that was generated, the renormalised distribution over the allowed digits."""
    digits = {str(i) for i in range(lo, hi + 1)}
    alternatives = "|".join(re.escape(k) for k in keys)
    after_key = re.compile(rf'"({alternatives})"\s*:\s*$')
    out: dict[str, dict[str, float]] = {}
    running = ""
    for piece, cands in zip(pieces, top_logprobs, strict=False):
        if piece.strip() in digits:
            m = after_key.search(running)
            if m and m.group(1) not in out:
                probs: dict[str, float] = {}
                for tok, lp in cands:
                    t = tok.strip()
                    if t in digits:
                        probs[t] = probs.get(t, 0.0) + math.exp(lp)
                z = sum(probs.values())
                if z > 0:
                    out[m.group(1)] = {k: v / z for k, v in sorted(probs.items())}
        running += piece
    return out


def expected_score(dist: dict[str, float]) -> float:
    return sum(int(k) * p for k, p in dist.items())


def as_score(value, lo: int = 1, hi: int = 5) -> int | None:
    """Accept 4, 4.0 or "4"; reject anything outside the scale."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and lo <= value <= hi else None
