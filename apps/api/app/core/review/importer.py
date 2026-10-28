"""Reviewer results -> ``Asset.critique["reviewer"]`` on the reviewed assets.

Each result line is an ``evaltrain`` prediction plus the request's ``ref``; the sidecar
``<results>.meta.json`` identifies the reviewer (base model, revision, adapter, prompt
version). Every stored review carries that identity and the reviewed asset version. An
asset whose version changed after export gets its findings marked ``stale``, and the
lesson view says so instead of presenting them as current.

Findings are advisory: approval state is never changed here.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.review.criteria import CRITERIA_VERSION
from app.models.asset import Asset


def expected_score(dist: dict | None) -> float | None:
    """Probability-weighted 1-5 score from the score-digit distribution, when present."""
    if not dist:
        return None
    total = sum(dist.values())
    return round(sum(int(k) * p for k, p in dist.items()) / total, 2) if total else None


def build_reviews(rows: list[dict], reviewer: dict) -> dict[str, dict]:
    """Group result rows by reviewed asset. Pure: rows and reviewer identity in, reviews out."""
    reviews: dict[str, dict] = {}
    for row in rows:
        ref = row.get("ref") or {}
        asset_id, kind, block = ref.get("asset_id"), ref.get("kind"), ref.get("block")
        if not asset_id or not kind:
            continue
        review = reviews.setdefault(asset_id, {**reviewer, "slides": {}, "rubric": [], "questions": {}})
        parsed = row.get("parsed") or {}
        valid = bool(row.get("valid"))
        dist = (row.get("score_dist") or {}).get("score")
        if kind == "slide":
            review["slides"][block] = {"valid": valid, "error": None if valid else row.get("error"), "issues": parsed.get("issues", []) if valid else []}
        elif kind == "rubric":
            review["rubric"].append({
                "criterion_id": block, "criterion": ref.get("criterion", block), "valid": valid,
                "score": parsed.get("score"), "expected": expected_score(dist), "feedback": parsed.get("feedback"),
            })
        elif kind == "question":
            review["questions"][block] = {"valid": valid, "score": parsed.get("score"), "expected": expected_score(dist)}
    return reviews


def reviewer_identity(meta: dict) -> dict:
    r = meta.get("reviewer", {})
    return {
        "source": "trained reviewer, batch job", "base_model": r.get("base_model"), "base_revision": r.get("base_revision"),
        "adapter": r.get("adapter"), "adapter_checkpoint": r.get("adapter_checkpoint"), "prompt_version": r.get("prompt_version"),
        "criteria_version": CRITERIA_VERSION, "reviewed_at": meta.get("finished_at"), "advisory": True,
    }


def import_results(db: Session, project_id: str, results: Path, meta: Path | None = None, manifest: Path | None = None) -> dict:
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
    meta = meta or results.with_suffix(results.suffix + ".meta.json")
    identity = reviewer_identity(json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {})
    exported = json.loads(manifest.read_text(encoding="utf-8")).get("assets", {}) if manifest and manifest.exists() else {}
    summary = {"assets": 0, "skipped_assets": [], "slides": 0, "issues": 0, "rubric": 0, "questions": 0, "invalid": sum(not r.get("valid") for r in rows), "stale": 0}
    for asset_id, review in build_reviews(rows, identity).items():
        asset = db.get(Asset, asset_id)
        if asset is None or asset.project_id != project_id:
            summary["skipped_assets"].append(asset_id)
            continue
        stale = asset_id in exported and exported[asset_id] != asset.version
        critique = dict(asset.critique or {})
        critique["reviewer"] = review | {"asset_version": exported.get(asset_id, asset.version), "stale": stale}
        asset.critique = critique  # reassign so SQLAlchemy persists the JSONB change
        summary["assets"] += 1
        summary["stale"] += stale
        summary["slides"] += len(review["slides"])
        summary["issues"] += sum(len(s["issues"]) for s in review["slides"].values())
        summary["rubric"] += len(review["rubric"])
        summary["questions"] += len(review["questions"])
    db.commit()
    return summary
