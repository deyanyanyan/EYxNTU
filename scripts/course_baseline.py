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
import io
import json
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import settings

DEFAULT_SOURCE = Path(__file__).resolve().parent / "fixtures" / "baseline_course.md"
POLL_SECONDS = 5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", type=Path, help="document to upload; repeatable (default: Northwind fixture)")
    ap.add_argument("--audience", default="New Northwind Analytics employees with no security background")
    ap.add_argument("--duration", type=int, default=30, help="course length in minutes; drives the lesson count")
    ap.add_argument("--goals", default="Follow the company's security rules in day-to-day work and know how to report an incident.")
    ap.add_argument("--keep", action="store_true", help="keep the project so it can be opened in the web UI")
    args = ap.parse_args()
    sources = args.source or [DEFAULT_SOURCE]

    record: dict = {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "llm_context_tokens": settings.llm_context_tokens,
        "llm_max_tokens": settings.llm_max_tokens,
        "embedding_model": settings.embedding_model,
        "sources": [p.name for p in sources],
        "brief": {"audience": args.audience, "duration_minutes": args.duration, "goals": args.goals},
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
            out = out_dir / f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
            out.write_text(json.dumps(record, indent=2))
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
