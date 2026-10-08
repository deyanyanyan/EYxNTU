"""Run the whole single-pass course pipeline once and record its numbers.

docker compose ... exec -T api python /srv/scripts/course_baseline.py [--source PATH ...] [--keep]

Creates a project, uploads the sources (default: the fictional Northwind handbook
in scripts/fixtures), waits for ingestion, then plans -> approves -> generates
lessons -> exports, downloads both export files and checks they open. Every
step's job result (counts, citation quality, model calls, seconds) is written to
DATA_DIR/artifacts/baselines/<timestamp>.json — the numbers the evaluation layer
will be compared against. Requires a pulled model; on a CPU laptop expect
15-30 minutes. The project is deleted afterwards unless --keep is given.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import subprocess
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select

from app.config import settings
from app.core.prompts.service import get_active
from app.db.session import SessionLocal
from app.models.asset import Asset, AssetKind
from app.models.chunk import Chunk
from app.models.source import Source

DEFAULT_SOURCE = Path(__file__).resolve().parent / "fixtures" / "baseline_course.md"
POLL_SECONDS = 5


def _json_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _redact_secrets(value):
    secrets = [secret for secret in (settings.llm_api_key, settings.judge_api_key) if secret and len(secret) >= 8]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_secrets(item) for key, item in value.items()}
    return value


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _snapshot_prompts() -> dict[str, dict]:
    snapshots: dict[str, dict] = {}
    with SessionLocal() as db:
        for task in ("plan", "slides", "quiz"):
            prompts = get_active(db, task)
            payload = {"task": task, "version_id": prompts.version_id, "system_prompt": prompts.system_prompt, "templates": prompts.templates}
            payload["sha256"] = _json_hash(payload)
            snapshots[task] = payload
    return snapshots


def _write_eval_bundle(
    *,
    run_id: str,
    project_id: str,
    plan: dict,
    client_request,
    sources: list[Path],
    brief: dict,
    data_classification: str,
    generator_arm: str,
    quantization: str | None,
    generation_record: dict,
    prompt_snapshots: dict[str, dict],
) -> Path:
    lesson_ids = [lesson["id"] for module in plan.get("modules", []) for lesson in module.get("lessons", [])]
    lesson_bundles: list[dict] = []
    for module in plan.get("modules", []):
        for lesson in module.get("lessons", []):
            detail = client_request("GET", f"/projects/{project_id}/lessons/{lesson['id']}")
            detail["module_title"] = module.get("title")
            lesson_bundles.append(detail)

    with SessionLocal() as db:
        assets = list(db.scalars(select(Asset).where(Asset.lesson_id.in_(lesson_ids), Asset.kind.in_([AssetKind.SLIDES.value, AssetKind.QUIZ.value])))) if lesson_ids else []
        assets_by_lesson_kind = {(asset.lesson_id, asset.kind): asset for asset in assets}
        reference_ids: set[str] = set()
        for detail in lesson_bundles:
            for key, kind in (("slides", AssetKind.SLIDES.value), ("quiz", AssetKind.QUIZ.value)):
                asset = assets_by_lesson_kind.get((detail["lesson"]["id"], kind))
                refs = ((asset.content or {}).get("references") or {}) if asset else {}
                for ref in refs.values():
                    if ref.get("chunk_id"):
                        reference_ids.add(ref["chunk_id"])
        chunk_rows = db.execute(
            select(Chunk, Source.filename).join(Source, Source.id == Chunk.source_id).where(Chunk.id.in_(reference_ids))
        ).all() if reference_ids else []
        chunks = {chunk.id: {"text": chunk.text, "source_name": filename, "source_id": chunk.source_id} for chunk, filename in chunk_rows}

        for detail in lesson_bundles:
            lesson_id = detail["lesson"]["id"]
            detail["evidence"] = {}
            detail["asset_provenance"] = {}
            for key, kind in (("slides", AssetKind.SLIDES.value), ("quiz", AssetKind.QUIZ.value)):
                asset = assets_by_lesson_kind.get((lesson_id, kind))
                content = (asset.content or {}) if asset else {}
                refs = content.get("references") or {}
                evidence = {}
                for number, ref in refs.items():
                    chunk_id = ref.get("chunk_id")
                    chunk = chunks.get(chunk_id)
                    evidence[str(number)] = {
                        **ref,
                        "rank": int(number) if str(number).isdigit() else None,
                        "text": chunk.get("text") if chunk else None,
                        "source_name": (chunk or {}).get("source_name", ref.get("source_name")),
                    }
                detail["evidence"][key] = evidence
                detail["asset_provenance"][key] = {
                    "asset_id": asset.id if asset else None,
                    "prompt_version_id": asset.prompt_version_id if asset else None,
                    "generated_with_model": asset.generated_with_model if asset else None,
                }

    source_manifest = []
    for source in sources:
        raw = source.read_bytes()
        source_manifest.append({"name": source.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})

    manifest = {
        "bundle_version": 1,
        "run_id": run_id,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "project_id": project_id,
        "data_classification": data_classification,
        "sources": source_manifest,
        "brief": brief,
        "brief_sha256": _json_hash(brief),
        "generator": {
            "arm": generator_arm,
            "model": settings.llm_model,
            "base_url": _safe_endpoint(settings.llm_base_url),
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "context_tokens": settings.llm_context_tokens,
            "timeout_seconds": settings.llm_timeout_seconds,
            "quantization": quantization,
        },
        "retrieval": {
            "embedding_model": settings.embedding_model,
            "embedding_dim": settings.embedding_dim,
            "top_k": settings.rag_top_k,
            "similarity_threshold": settings.rag_similarity_threshold,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
        },
        "prompt_hashes": {task: prompt["sha256"] for task, prompt in prompt_snapshots.items()},
        "generation": _redact_secrets(generation_record),
        "runtime": {"platform": platform.platform(), "machine": platform.machine()},
    }
    course_snapshot = {"plan": plan, "lessons": lesson_bundles}
    manifest["prompts_sha256"] = _json_hash(prompt_snapshots)
    manifest["course_sha256"] = _json_hash(course_snapshot)
    bundle_dir = settings.artifacts_dir / "eval" / "runs" / run_id
    # A captured run is an immutable benchmark input. Never silently replace it.
    bundle_dir.mkdir(parents=True, exist_ok=False)
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (bundle_dir / "prompts.json").write_text(json.dumps(prompt_snapshots, ensure_ascii=False, indent=2), encoding="utf-8")
    (bundle_dir / "course.json").write_text(
        json.dumps(course_snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return bundle_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", type=Path, help="document to upload; repeatable (default: Northwind fixture)")
    ap.add_argument("--audience", default="New Northwind Analytics employees with no security background")
    ap.add_argument("--duration", type=int, default=30, help="course length in minutes; drives the lesson count")
    ap.add_argument("--goals", default="Follow the company's security rules in day-to-day work and know how to report an incident.")
    ap.add_argument("--keep", action="store_true", help="keep the project so it can be opened in the web UI")
    ap.add_argument("--capture-eval-inputs", action="store_true", help="save a local run bundle for separate batch evaluation")
    ap.add_argument("--generator-arm", help="label this run for later comparisons (defaults to the configured model id)")
    ap.add_argument("--quantization", help="optional metadata label such as Q4_K_M; does not change model serving")
    ap.add_argument(
        "--eval-data-classification",
        choices=("fictional", "public", "local-only", "unknown"),
        default="unknown",
        help="label the data in a captured evaluation bundle; only public/fictional bundles can be sent to a hosted judge",
    )
    args = ap.parse_args()
    if args.capture_eval_inputs and args.eval_data_classification == "unknown":
        ap.error("--capture-eval-inputs requires --eval-data-classification (fictional, public, or local-only).")
    sources = args.source or [DEFAULT_SOURCE]
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    brief = {"audience": args.audience, "duration_minutes": args.duration, "goals": args.goals}
    prompt_snapshots = _snapshot_prompts() if args.capture_eval_inputs else {}

    record: dict = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "llm_context_tokens": settings.llm_context_tokens,
        "llm_max_tokens": settings.llm_max_tokens,
        "embedding_model": settings.embedding_model,
        "sources": [p.name for p in sources],
        "brief": brief,
        "steps": {},
    }
    started = time.perf_counter()

    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120) as client:
        def request(method: str, path: str, **kw):
            r = client.request(method, path, **kw)
            if r.is_error:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r

        token = request("POST", "/auth/token", data={"username": settings.default_admin_email, "password": settings.default_admin_password})
        client.headers["Authorization"] = "Bearer " + token["access_token"]

        def wait(job: dict, label: str) -> dict:
            last = None
            while True:
                job = request("GET", f"/jobs/{job['id']}")
                msg = job.get("message")
                if msg and msg != last:
                    print(f"  [{label}] {msg}", flush=True)
                    last = msg
                if job["status"] in ("completed", "failed", "cancelled"):
                    if job["status"] != "completed":
                        raise RuntimeError(f"{label} {job['status']}: {(job.get('error_message') or '').splitlines()[0] if job.get('error_message') else job.get('error_type')}")
                    return job
                time.sleep(POLL_SECONDS)

        project = request("POST", "/projects", json={
            "name": "Baseline " + uuid.uuid4().hex[:6],
            "target_audience": args.audience,
            "duration_minutes": args.duration,
            "learning_goals": args.goals,
        })
        pid = project["id"]
        record["project_id"] = pid
        print(f"project {pid}", flush=True)
        try:
            t = time.perf_counter()
            for path in sources:
                request("POST", f"/projects/{pid}/sources", files={"file": (path.name, path.read_bytes())})
            for job in request("GET", f"/jobs?project_id={pid}&recent_minutes=10"):
                if job["kind"] == "ingest_source":
                    wait(job, "ingest")
            record["steps"]["ingest"] = {"seconds": round(time.perf_counter() - t, 1)}

            print("planning…", flush=True)
            plan_job = wait(request("POST", f"/projects/{pid}/plan"), "plan")
            record["steps"]["plan"] = plan_job["result"]
            plan = request("GET", f"/projects/{pid}/plan")
            request("POST", f"/projects/{pid}/plan/{plan['id']}/approve")
            record["plan_outline"] = [
                {"module": m["title"], "lessons": [le["title"] for le in m["lessons"]]} for m in plan["modules"]
            ]

            print("generating lessons…", flush=True)
            lessons_job = wait(request("POST", f"/projects/{pid}/lessons/generate"), "lessons")
            record["steps"]["lessons"] = lessons_job["result"]
            if args.capture_eval_inputs:
                bundle_dir = _write_eval_bundle(
                    run_id=run_id,
                    project_id=pid,
                    plan=plan,
                    client_request=request,
                    sources=sources,
                    brief=brief,
                    data_classification=args.eval_data_classification,
                    generator_arm=args.generator_arm or settings.llm_model,
                    quantization=args.quantization,
                    generation_record=lessons_job["result"],
                    prompt_snapshots=prompt_snapshots,
                )
                record["evaluation_bundle"] = str(bundle_dir)
                print(f"evaluation input bundle written to {bundle_dir}", flush=True)

            print("exporting…", flush=True)
            export_job = wait(request("POST", f"/projects/{pid}/export"), "export")
            record["steps"]["export"] = export_job["result"]
            asset_id = export_job["result"]["asset_id"]

            scorm = request("GET", f"/projects/{pid}/exports/{asset_id}/files/scorm").content
            names = zipfile.ZipFile(io.BytesIO(scorm)).namelist()
            assert "imsmanifest.xml" in names, "SCORM package has no manifest"
            pptx = request("GET", f"/projects/{pid}/exports/{asset_id}/files/pptx").content
            from pptx import Presentation

            record["files"] = {
                "scorm_bytes": len(scorm),
                "scorm_lesson_pages": sum(1 for n in names if n.startswith("lessons/")),
                "pptx_bytes": len(pptx),
                "pptx_slides": len(Presentation(io.BytesIO(pptx)).slides),
            }
            record["status"] = "completed"
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            raise
        finally:
            record["total_seconds"] = round(time.perf_counter() - started, 1)
            out_dir = settings.artifacts_dir / "baselines"
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{run_id}.json"
            out.write_text(json.dumps(_redact_secrets(record), indent=2), encoding="utf-8")
            print(f"record written to {out}", flush=True)
            if args.keep:
                print(f"kept project {pid} — open it in the web UI", flush=True)
            else:
                request("DELETE", f"/projects/{pid}")

    lessons = record["steps"]["lessons"]
    print("\nBASELINE")
    print(f"  plan     {record['steps']['plan']['lessons']} lessons / {record['steps']['plan']['modules']} modules, "
          f"{record['steps']['plan']['llm_calls']} calls, {record['steps']['plan']['seconds']} s")
    print(f"  lessons  {lessons['decks']} decks, {lessons['slides']} slides, {lessons['questions_accepted']} questions "
          f"({lessons['questions_rejected']} rejected), {lessons['llm_calls']} calls, {lessons['seconds']} s")
    print(f"  grounding {lessons['bullets_without_citation']}/{lessons['bullets_checked']} content bullets uncited, "
          f"{lessons['invalid_citation_numbers']} citations point nowhere, {len(lessons['errors'])} failed steps")
    print(f"  export   {record['files']['pptx_slides']} PPTX slides, {record['files']['scorm_lesson_pages']} SCORM lesson pages")
    print(f"  total    {record['total_seconds']} s")


if __name__ == "__main__":
    main()
