"""RAGTruth: human-annotated unsupported or conflicting spans in generated responses.

The reviewer sees the exact prompt and source material the writer was given and the
writer's response, and must quote every conflicting ("conflict") or unsupported
("baseless") span. Targets are the annotated spans in order of appearance, with the
annotated type and the ``implicit_true`` flag (unsupported by the source but probably
true; still a grounding failure, but not a proven falsehood).

Only responses with ``quality == "good"`` are used, as in the released baseline.
Splits keep every source's six responses together: the official per-source split
supplies the test partition (re-audited here for shared sources), and 10% of the
official training sources, chosen by hash, form the development partition.

Scoring follows the RAGTruth paper: response-level precision/recall/F1 for "contains
a hallucination", and character-overlap span precision/recall/F1 (micro-averaged over
all characters). Predicted quotes are mapped back to offsets in the response; quotes
that are not in the response score no overlap and are counted separately.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from evaltrain import metrics as M
from evaltrain.prompts import GROUNDING, GROUNDING_TYPES, chat
from evaltrain.records import Example, dump_target, read_jsonl
from evaltrain.splits import assign, audit_leakage, text_key
from evaltrain.tasks import Task

NAME = "ragtruth_grounding"
TYPE_MAP = {"Evident Conflict": "evident_conflict", "Subtle Conflict": "subtle_conflict", "Evident Baseless Info": "evident_baseless", "Subtle Baseless Info": "subtle_baseless"}
_TRAILER = re.compile(r"\n(?:output|Overview|Answer):\s*$")


def _context(prompt: str) -> str:
    """The writer's prompt minus its trailing generation cue (``output:``, ``Overview:``)."""
    return _TRAILER.sub("", prompt.rstrip())


def build(raw_dir: Path, cfg: dict) -> tuple[list[Example], dict]:
    salt = cfg.get("salt", "evaltrain-v1")
    dev_fraction = cfg.get("ragtruth_dev_fraction", 0.10)
    base = raw_dir / "ragtruth" / "dataset"
    sources = {s["source_id"]: s for s in read_jsonl(base / "source_info.jsonl")}
    responses = list(read_jsonl(base / "response.jsonl"))

    official: dict[str, set[str]] = defaultdict(set)
    for r in responses:
        official[r["source_id"]].add(r["split"])
    straddling = sorted(s for s, splits in official.items() if len(splits) > 1)
    if straddling:
        raise ValueError(f"{len(straddling)} RAGTruth sources occur in both official splits, e.g. {straddling[:5]}")

    record: dict = {"source_rows": len(responses), "sources": len(sources), "quality": dict(Counter(r["quality"] for r in responses)), "dropped": Counter()}
    examples = []
    for r in responses:
        if r["quality"] != "good":
            record["dropped"][f"quality_{r['quality']}"] += 1
            continue
        s = sources[r["source_id"]]
        labels = sorted(r["labels"], key=lambda lab: (lab["start"], lab["end"]))
        for lab in labels:
            if r["response"][lab["start"] : lab["end"]] != lab["text"]:
                raise ValueError(f"RAGTruth response {r['id']}: span offsets do not match span text")
        if r["split"] == "test":
            split = "test"
        else:
            split = assign(f"ragtruth:{r['source_id']}", salt, {"train": 1 - dev_fraction, "dev": dev_fraction})
        issues = [{"span": lab["text"], "type": TYPE_MAP[lab["label_type"]], "implicit_true": bool(lab["implicit_true"])} for lab in labels]
        examples.append(
            Example(
                id=f"ragtruth:{r['id']}", task=NAME, dataset="ragtruth", split=split, group=f"ragtruth:{r['source_id']}",
                messages=chat(GROUNDING.format(context=_context(s["prompt"]), response=r["response"])),
                target=dump_target({"issues": issues}),
                gold={
                    "response": r["response"], "spans": [[lab["start"], lab["end"]] for lab in labels], "types": [i["type"] for i in issues],
                    "implicit_true": [i["implicit_true"] for i in issues], "due_to_null": [bool(lab.get("due_to_null")) for lab in labels],
                    "notes": [lab.get("meta") for lab in labels], "task_type": s["task_type"], "subset": s["task_type"],
                },
                meta={"source": "ragtruth", "response_id": r["id"], "source_id": r["source_id"], "writer_model": r["model"], "official_split": r["split"],
                      "label_origin": "human", "response_key": text_key(r["response"])},
            )
        )
    by_split = defaultdict(list)
    for e in examples:
        by_split[e.split].append(e)
    record |= {
        "dropped": dict(record["dropped"]),
        "split_rows": {k: len(v) for k, v in sorted(by_split.items())},
        "split_groups": {k: len({e.group for e in v}) for k, v in sorted(by_split.items())},
        "with_hallucination": {k: sum(bool(e.gold["spans"]) for e in v) for k, v in sorted(by_split.items())},
        "task_types": {k: dict(Counter(e.gold["task_type"] for e in v)) for k, v in sorted(by_split.items())},
        # Identical *inputs* would be leakage; short canned responses ("Unable to answer based on
        # given passages.", 107 QA rows over different questions) legitimately recur across splits.
        "leakage": {
            "all_splits": audit_leakage(
                [{"split": e.split, "group": e.group, "input": text_key(e.messages[1]["content"]),
                  "resp": e.meta["response_key"] if len(e.gold["response"]) >= 100 else None} for e in examples],
                {"source": lambda r: [r["group"]], "identical_input": lambda r: [r["input"]], "identical_long_response": lambda r: [r["resp"]] if r["resp"] else []},
            )
        },
    }
    return examples, record


def parse(obj: dict) -> dict:
    issues = obj.get("issues")
    if not isinstance(issues, list):
        raise ValueError("issues must be a list")
    out = []
    for it in issues:
        if not isinstance(it, dict) or not isinstance(it.get("span"), str) or not it["span"].strip():
            raise ValueError("each issue needs a non-empty 'span' string")
        t = it.get("type")
        imp = it.get("implicit_true", False)
        out.append({"span": it["span"], "type": t if t in GROUNDING_TYPES else f"unknown:{t}", "implicit_true": imp if isinstance(imp, bool) else None})
    return {"issues": out}


def _located_issues(row: dict) -> list[tuple[dict, tuple[int, int] | None]]:
    """Each predicted issue with its offsets in the response (``None`` if not found); cached on the row."""
    if "_located" not in row:
        issues = (row["pred"] or {}).get("issues", [])
        row["_located"] = list(zip(issues, M.locate_each(row["gold"]["response"], [i["span"] for i in issues]), strict=True))
    return row["_located"]


def _pred_spans(row: dict) -> tuple[list[tuple[int, int]], int, int]:
    """Located predicted spans, number of quotes, number of quotes not found in the response."""
    pairs = _located_issues(row)
    located = [span for _, span in pairs if span is not None]
    return located, len(pairs), len(pairs) - len(located)


def _response_prf(rows: list[dict]) -> dict:
    return M.response_level_prf([bool(r["gold"]["spans"]) for r in rows], [bool((r["pred"] or {}).get("issues")) for r in rows])


def _span_prf(rows: list[dict]) -> dict:
    return M.char_span_prf([[tuple(s) for s in r["gold"]["spans"]] for r in rows], [_pred_spans(r)[0] for r in rows])


def _coarse(t: str) -> str:
    return "conflict" if "conflict" in t else ("baseless" if "baseless" in t else "unknown")


def _type_agreement(rows: list[dict]) -> float:
    """Among predicted spans that overlap a gold span, share whose conflict/baseless class matches."""
    hits = agree = 0
    for r in rows:
        for issue, span in _located_issues(r):
            if span is None:
                continue
            ps, pe = span
            for (gs, ge), gt in zip(r["gold"]["spans"], r["gold"]["types"], strict=True):
                if ps < ge and gs < pe:
                    hits += 1
                    agree += _coarse(issue["type"]) == _coarse(gt)
                    break
    return agree / hits if hits else float("nan")


def point_metrics(rows: list[dict]) -> dict:
    out = {}
    for subset in sorted({r["gold"]["task_type"] for r in rows}) + ["all"]:
        sub = [r for r in rows if subset == "all" or r["gold"]["task_type"] == subset]
        quotes = sum(_pred_spans(r)[1] for r in sub)
        missing = sum(_pred_spans(r)[2] for r in sub)
        out[subset] = {
            "n_rows": len(sub), "response": _response_prf(sub), "span_char": _span_prf(sub), "predicted_quotes": quotes,
            "unlocated_quote_rate": missing / quotes if quotes else float("nan"), "coarse_type_agreement": _type_agreement(sub),
        }
    return out


TASK = Task(
    name=NAME,
    dataset="ragtruth",
    build=build,
    parse=parse,
    point_metrics=point_metrics,
    ci_metrics={
        "response_f1": lambda rs: _response_prf(rs)["f1"],
        "response_precision": lambda rs: _response_prf(rs)["precision"],
        "response_recall": lambda rs: _response_prf(rs)["recall"],
        "span_char_f1": lambda rs: _span_prf(rs)["f1"],
    },
    max_new_tokens=768,
)
