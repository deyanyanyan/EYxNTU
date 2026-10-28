"""LecEval: a lecture slide (image) and its spoken explanation (transcript), rated 1-5
by three annotators on four criteria. Opt-in: see ``acquire.py`` for the asset terms.

The criterion definitions are the ones in the dataset's own annotation prompt, under
the dataset's field names. The reviewer must see the slide image: the same ratings
are not valid labels for a transcript-only input.

Multiple raters: each training item contributes one example per annotator with that
annotator's four ratings, which under the usual token cross-entropy is equivalent to
training on the empirical rater distribution. Development and test items appear once,
scored against the mean of the in-scale ratings per criterion (the aggregation rule
the report states). Ratings outside 1-5 (one documented 6) are dropped and counted.

Splits are by lecture (``{course}_{lecture}``), so no lecture's slides straddle
partitions; the paper's 420-pair evaluation subset was not released.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from evaltrain import metrics as M
from evaltrain.parsing import as_score, expected_score
from evaltrain.prompts import SLIDE, chat
from evaltrain.records import Example, dump_target, read_jsonl
from evaltrain.splits import assign, audit_leakage, text_key
from evaltrain.tasks import Task

NAME = "leceval_slides"
CRITERIA = (
    ("content_relevance", "How accurately does the transcript represent the information on the slide?"),
    ("expressive_clarity", "How clear and understandable is the language used in the transcript?"),
    ("logical_structure", "How well is the transcript structured and organized?"),
    ("audience_engagement", "How inspiring and engaging is the transcript?"),
)
KEYS = tuple(k for k, _ in CRITERIA)


def _prompt(transcript: str) -> str:
    criteria = "\n".join(f"- {k}: {d}" for k, d in CRITERIA)
    keys = ", ".join(f'"{k}": <integer 1-5>' for k in KEYS)
    return SLIDE.format(criteria=criteria, transcript=transcript.strip(), keys=keys)


def build(raw_dir: Path, cfg: dict) -> tuple[list[Example], dict]:
    salt = cfg.get("salt", "evaltrain-v1")
    fractions = cfg.get("leceval_fractions", {"train": 0.7, "dev": 0.15, "test": 0.15})
    root = raw_dir / "leceval"
    rows = [r for path in sorted((root / "dataset").glob("*/metadata.jsonl")) for r in read_jsonl(path)]
    if not rows:
        raise FileNotFoundError(f"no LecEval metadata under {root}/dataset (acquire with --include leceval)")
    record: dict = {"source_rows": len(rows), "dropped": Counter(), "out_of_scale_ratings": []}
    examples = []
    for r in rows:
        course, lecture = r["id"].split("_slide_")[0].rsplit("_", 1)
        lecture_key = f"{course}_{lecture}"
        image = r["slide"].lstrip("/")
        if not (root / image).is_file():
            record["dropped"]["missing_image"] += 1
            continue
        split = assign(f"leceval:{lecture_key}", salt, fractions)
        ratings = {k: list(r["rate"][k]) for k in KEYS}
        for k, vals in ratings.items():
            for j, v in enumerate(vals):
                if not (isinstance(v, int) and 1 <= v <= 5):
                    record["out_of_scale_ratings"].append({"id": r["id"], "criterion": k, "rater": j, "value": v})
        n_raters = len(ratings[KEYS[0]])
        valid = {k: [v for v in vals if isinstance(v, int) and 1 <= v <= 5] for k, vals in ratings.items()}
        mean = {k: sum(v) / len(v) for k, v in valid.items() if v}
        common = dict(task=NAME, dataset="leceval", split=split, group=f"leceval:{lecture_key}", messages=chat(_prompt(r["transcript"])), images=[image])
        meta = {"source": "leceval", "item_id": r["id"], "lecture": lecture_key, "label_origin": "human ratings", "transcript_key": text_key(r["transcript"])}
        if split == "train":
            for j in range(n_raters):
                vec = {k: ratings[k][j] for k in KEYS}
                if not all(isinstance(v, int) and 1 <= v <= 5 for v in vec.values()):
                    record["dropped"]["train_rater_vector_out_of_scale"] += 1
                    continue
                examples.append(Example(id=f"leceval:{r['id']}:r{j}", target=dump_target(vec), gold={"ratings": vec, "subset": "train"}, meta=meta | {"rater": j}, **common))
        else:
            examples.append(Example(id=f"leceval:{r['id']}", target=None, gold={"mean": mean, "ratings": ratings, "subset": split}, meta=meta, **common))
    by_split = defaultdict(list)
    for e in examples:
        by_split[e.split].append(e)
    record |= {
        "dropped": dict(record["dropped"]),
        "split_rows": {k: len(v) for k, v in sorted(by_split.items())},
        "split_lectures": {k: len({e.group for e in v}) for k, v in sorted(by_split.items())},
        "aggregation": "dev/test gold = mean of in-scale ratings per criterion; train = one example per annotator",
        "leakage": {
            "all_splits": audit_leakage(
                [{"split": e.split, "group": e.group, "t": e.meta["transcript_key"]} for e in examples],
                {"lecture": lambda r: [r["group"]], "identical_transcript": lambda r: [r["t"]]},
            )
        },
    }
    return examples, record


def parse(obj: dict) -> dict:
    out = {}
    for k in KEYS:
        v = as_score(obj.get(k))
        if v is None:
            raise ValueError(f"{k} must be an integer 1-5, got {obj.get(k)!r}")
        out[k] = v
    return out


def _pairs(rows: list[dict], key: str, expected: bool = False):
    g, p = [], []
    for r in rows:
        if r["pred"] is None or key not in r["gold"].get("mean", {}):
            continue
        if expected:
            d = r["dist"].get(key)
            if not d:
                continue
            p.append(expected_score(d))
        else:
            p.append(r["pred"][key])
        g.append(r["gold"]["mean"][key])
    return g, p


def point_metrics(rows: list[dict]) -> dict:
    out = {}
    for k in KEYS:
        g, p = _pairs(rows, k)
        ge, pe = _pairs(rows, k, expected=True)
        rep = {"n": len(g), "mae_vs_mean": M.mae(g, p), "pearson": M.pearson(g, p), "spearman": M.spearman(g, p), "kendall": M.kendall(g, p)}
        if pe:
            rep |= {"spearman_expected": M.spearman(ge, pe), "pearson_expected": M.pearson(ge, pe), "mae_expected": M.mae(ge, pe)}
        out[k] = rep
    return out


TASK = Task(
    name=NAME,
    dataset="leceval",
    build=build,
    parse=parse,
    point_metrics=point_metrics,
    ci_metrics={f"spearman_{k}": (lambda rs, k=k: M.spearman(*_pairs(rs, k))) for k in KEYS},
    score_keys=KEYS,
    max_new_tokens=64,
    multimodal=True,
)
