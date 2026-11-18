"""Summarise reviewer results per course, and agreement between two reviewers.

    python summarize.py course LABEL=results.jsonl [LABEL=results.jsonl ...]
    python summarize.py agree A=results.jsonl B=results.jsonl
"""
import json
import statistics as st
import sys
from collections import Counter


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def score(r):
    """Probability-weighted score when available (as the app shows), else the parsed score."""
    dist = (r.get("score_dist") or {}).get("score")
    if dist:
        return sum(int(k) * v for k, v in dist.items()) / sum(dist.values())
    return (r.get("parsed") or {}).get("score")


def course(rows):
    slides = [r for r in rows if r["task"] == "ragtruth_grounding"]
    rubric = [r for r in rows if r["task"] == "prometheus_rubric"]
    quiz = [r for r in rows if r["task"] == "oak_distractors"]
    flagged = [r for r in slides if r["valid"] and r["parsed"]["issues"]]
    types = Counter(i.get("type") for r in flagged for i in r["parsed"]["issues"])
    by_criterion = {}
    for r in rubric:
        crit = (r.get("ref") or {}).get("criterion") or (r.get("ref") or {}).get("block") or "rubric"
        if score(r) is not None:
            by_criterion.setdefault(crit, []).append(score(r))
    q = [score(r) for r in quiz if score(r) is not None]
    return {
        "checks": len(rows), "valid": sum(r["valid"] for r in rows),
        "slides": len(slides), "slides_flagged": len(flagged),
        "share_flagged": round(len(flagged) / len(slides), 3) if slides else None,
        "issues": sum(types.values()), "issue_types": dict(types),
        "rubric_mean": {k: round(st.mean(v), 2) for k, v in by_criterion.items()},
        "quiz_distractor_mean": round(st.mean(q), 2) if q else None,
        "quiz_weak_le_2": sum(1 for s in q if s <= 2), "quiz_n": len(q),
        "examples": [{"span": i.get("span"), "type": i.get("type")} for r in flagged for i in r["parsed"]["issues"]][:8],
    }


def agree(a_rows, b_rows):
    a = {r["id"]: r for r in a_rows}
    b = {r["id"]: r for r in b_rows}
    both = [i for i in a if i in b and a[i]["valid"] and b[i]["valid"]]
    g = [i for i in both if a[i]["task"] == "ragtruth_grounding"]
    flag = lambda r: bool(r["parsed"]["issues"])
    g_agree = sum(flag(a[i]) == flag(b[i]) for i in g)
    out = {"compared": len(both), "slides": len(g), "slide_flag_agreement": f"{g_agree}/{len(g)}",
           "slides_flagged_A": sum(flag(a[i]) for i in g), "slides_flagged_B": sum(flag(b[i]) for i in g),
           "slide_disagreements": [{"id": i, "A": a[i]["parsed"]["issues"], "B": b[i]["parsed"]["issues"]} for i in g if flag(a[i]) != flag(b[i])]}
    for task in ("prometheus_rubric", "oak_distractors"):
        ids = [i for i in both if a[i]["task"] == task]
        pairs = [(score(a[i]), score(b[i])) for i in ids]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if pairs:
            out[task] = {"n": len(pairs), "mean_abs_diff": round(st.mean(abs(x - y) for x, y in pairs), 2),
                         "within_1": sum(abs(x - y) <= 1 for x, y in pairs),
                         "pairs": [(round(x, 2), round(y, 2)) for x, y in pairs]}
    return out


if __name__ == "__main__":
    mode, args = sys.argv[1], dict(a.split("=", 1) for a in sys.argv[2:])
    if mode == "course":
        print(json.dumps({k: course(load(v)) for k, v in args.items()}, indent=1, ensure_ascii=False))
    else:
        (la, pa), (lb, pb) = list(args.items())
        print(json.dumps({"A": la, "B": lb, **agree(load(pa), load(pb))}, indent=1, ensure_ascii=False))
