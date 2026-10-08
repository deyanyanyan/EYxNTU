"""Score saved course run bundles without calling the generation pipeline.

Run inside the API container, for example:
  python /srv/scripts/evaluate_batch.py /data/artifacts/eval/runs/<run-id> --judge
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.config import settings
from app.core.evaluation.service import score_bundle, score_means
from app.core.llm.client import judge_target, run_blocking
from app.core.prompts.service import load_file_defaults


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_bundle(path: Path) -> dict[str, Any]:
    bundle_dir = path if path.is_dir() else path.parent
    manifest_path = bundle_dir / "manifest.json"
    course_path = bundle_dir / "course.json"
    if not manifest_path.is_file() or not course_path.is_file():
        raise ValueError(f"{path} is not a run bundle (expected manifest.json and course.json)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    course = json.loads(course_path.read_text(encoding="utf-8"))
    prompt_path = bundle_dir / "prompts.json"
    if prompt_path.is_file():
        prompts = json.loads(prompt_path.read_text(encoding="utf-8"))
    else:
        prompts = None
    for hash_key, snapshot, label in (
        ("course_sha256", course, "course.json"),
        ("prompts_sha256", prompts, "prompts.json"),
    ):
        expected = manifest.get(hash_key)
        if expected and snapshot is None:
            raise ValueError(f"{bundle_dir / label} is missing but its manifest contains a hash")
        if expected and _canonical_hash(snapshot) != expected:
            raise ValueError(f"{bundle_dir / label} does not match its manifest hash")
    return {"path": str(bundle_dir), "manifest": manifest, "course": course}


def _prompt_hash(prompt_set) -> str:
    canonical = json.dumps(
        {"task": prompt_set.task, "system_prompt": prompt_set.system_prompt, "templates": prompt_set.templates},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _sum_reported(rows: list[dict[str, Any]], field: str) -> int | None:
    values = [((row.get("judge") or {}).get("usage") or {}).get(field) for row in rows]
    if not values or any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def _write_reports(output_dir: Path, results: list[dict[str, Any]], course_results: list[dict[str, Any]]) -> None:
    fields = [
        "run_id", "generator_model", "generation_calls", "generation_seconds", "lesson_id", "lesson_title", "judge_model", "judge_status",
        "grounding", "coherence", "pedagogy", "judge_calls", "judge_prompt_tokens", "judge_completion_tokens",
        "judge_latency_ms", "citations_invalid", "citation_references_missing_text", "bullets_checked",
        "bullets_uncited", "bullets_low_lexical_overlap", "slides_over_density_limit", "quiz_accepted",
        "quiz_rejected", "quiz_span_not_found",
    ]
    csv_path = output_dir / "summary.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in results:
            judge = row.get("judge") or {}
            dimensions = judge.get("dimensions") or {}
            checks = (row.get("checks") or {}).get("counts") or {}
            usage = judge.get("usage") or {}
            generation = row.get("generation") or {}
            writer.writerow({
                "run_id": row.get("run_id"),
                "generator_model": (row.get("generator") or {}).get("model"),
                "generation_calls": generation.get("llm_calls"),
                "generation_seconds": generation.get("seconds"),
                "lesson_id": row.get("lesson_id"),
                "lesson_title": row.get("title"),
                "judge_model": judge.get("model"),
                "judge_status": judge.get("status"),
                "grounding": (dimensions.get("grounding") or {}).get("score"),
                "coherence": (dimensions.get("coherence") or {}).get("score"),
                "pedagogy": (dimensions.get("pedagogy") or {}).get("score"),
                "judge_calls": usage.get("calls"),
                "judge_prompt_tokens": usage.get("prompt_tokens"),
                "judge_completion_tokens": usage.get("completion_tokens"),
                "judge_latency_ms": usage.get("latency_ms"),
                **{name: checks.get(name) for name in fields if name in checks},
            })

    lines = [
        "# Batch evaluation summary",
        "",
        "Scores are descriptive measurements of saved model outputs. This report emits no pass/fail or workflow action.",
        "Dimension SD is the population spread across lessons within that run; it is not run-to-run variability.",
        "",
        "| Run | Generator | Lessons | Grounding | Coherence | Pedagogy | Gen calls | Gen sec | Judge calls | Judge sec | Judge prompt tokens | Judge completion tokens | Uncited bullets | Invalid citations | Quiz span issues | Shared cited chunks | Near-duplicate bullets |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for course in course_results:
        run_id = course.get("run_id")
        run_rows = [row for row in results if row.get("run_id") == run_id]
        means = score_means(run_rows)
        overlap = course.get("course_overlap") or {}
        checks = course.get("check_totals") or {}
        spreads = course.get("judge_lesson_score_stddev") or {}
        generation = course.get("generation") or {}
        judge_calls = _sum_reported(run_rows, "calls")
        judge_seconds = _sum_reported(run_rows, "latency_ms")
        judge_prompt_tokens = _sum_reported(run_rows, "prompt_tokens")
        judge_completion_tokens = _sum_reported(run_rows, "completion_tokens")
        score_cells = [
            f"{means[name]:.3f} (SD {spreads[name]:.3f})" if means[name] is not None and spreads.get(name) is not None
            else f"{means[name]:.3f}" if means[name] is not None
            else "n/a"
            for name in ("grounding", "coherence", "pedagogy")
        ]
        lines.append(
            f"| {run_id} | {(course.get('generator') or {}).get('model') or 'unknown'} | {course.get('lessons_scored', 0)} "
            f"| {score_cells[0]} | {score_cells[1]} | {score_cells[2]} "
            f"| {generation.get('llm_calls', 'n/a')} | {generation.get('seconds', 'n/a')} "
            f"| {judge_calls if judge_calls is not None else 'n/a'} "
            f"| {round(judge_seconds / 1000, 1) if judge_seconds is not None else 'n/a'} "
            f"| {judge_prompt_tokens if judge_prompt_tokens is not None else 'n/a'} "
            f"| {judge_completion_tokens if judge_completion_tokens is not None else 'n/a'} "
            f"| {checks.get('bullets_uncited', 0)} | {checks.get('citations_invalid', 0)} | {checks.get('quiz_span_not_found', 0)} "
            f"| {overlap.get('shared_cited_chunks', 0)} | {overlap.get('near_duplicate_bullet_pairs', 0)} |"
        )
    lines.extend(["", "Per-lesson scores, issue details, and judge usage are in scores.jsonl. Course overlap details are in courses.jsonl.", ""])
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


async def _score_all(bundles, prompts, prompt_hash, target):
    results: list[dict[str, Any]] = []
    course_results: list[dict[str, Any]] = []
    for bundle in bundles:
        run_id = (bundle.get("manifest") or {}).get("run_id") or Path(bundle["path"]).name
        print(f"scoring run {run_id} ({len((bundle.get('course') or {}).get('lessons') or [])} lessons)", flush=True)
        run_results, course_result = await score_bundle(bundle, prompts=prompts, prompt_hash=prompt_hash, target=target)
        results.extend(run_results)
        course_results.append(course_result)
    return results, course_results


def main() -> None:
    parser = argparse.ArgumentParser(description="Score saved LMS Studio run bundles as a separate batch.")
    parser.add_argument("bundles", nargs="+", type=Path, help="run bundle directories or their manifest.json paths")
    parser.add_argument("--judge", action="store_true", help="also score with the separately configured JUDGE_* target")
    parser.add_argument("--output-dir", type=Path, help="batch output directory (default: DATA_DIR/artifacts/eval/batches/<id>)")
    args = parser.parse_args()

    try:
        bundles = [_read_bundle(path) for path in args.bundles]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    target = None
    if args.judge:
        target = judge_target()
        if target is None:
            parser.error("--judge requires JUDGE_BASE_URL, JUDGE_API_KEY, and JUDGE_MODEL; no generator fallback is used.")
        non_public = [
            (bundle.get("manifest") or {}).get("run_id", bundle["path"])
            for bundle in bundles
            if (bundle.get("manifest") or {}).get("data_classification") not in {"public", "fictional"}
        ]
        if non_public:
            parser.error(f"Refusing hosted judging for bundles not marked public/fictional: {', '.join(non_public)}")

    prompts = load_file_defaults("critique")
    prompt_hash = _prompt_hash(prompts)
    batch_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output_dir = args.output_dir or settings.artifacts_dir / "eval" / "batches" / batch_id
    output_dir.mkdir(parents=True, exist_ok=False)

    results, course_results = run_blocking(_score_all(bundles, prompts, prompt_hash, target))
    _write_jsonl(output_dir / "scores.jsonl", results)
    _write_jsonl(output_dir / "courses.jsonl", course_results)
    _write_reports(output_dir, results, course_results)
    if target:
        prompt_snapshot = {
            "task": prompts.task,
            "system_prompt": prompts.system_prompt,
            "templates": prompts.templates,
            "sha256": prompt_hash,
        }
        (output_dir / "judge_prompt.json").write_text(
            json.dumps(prompt_snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    batch_manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "input_runs": [
            {
                "run_id": (bundle.get("manifest") or {}).get("run_id"),
                "generator": (bundle.get("manifest") or {}).get("generator"),
                "data_classification": (bundle.get("manifest") or {}).get("data_classification"),
            }
            for bundle in bundles
        ],
        "judge": {
            "model": target.model,
            "base_url": _safe_endpoint(target.base_url),
            "temperature": target.temperature,
            "max_tokens": target.max_tokens,
            "context_tokens": target.context_tokens,
            "timeout_seconds": target.timeout_seconds,
            "prompt_sha256": prompt_hash,
        } if target else None,
        "output_files": ["scores.jsonl", "courses.jsonl", "summary.csv", "summary.md"] + (["judge_prompt.json"] if target else []),
    }
    (output_dir / "manifest.json").write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"batch report written to {output_dir}", flush=True)


if __name__ == "__main__":
    main()
