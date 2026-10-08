"""Admin access to local benchmark runs and batch evaluation artifacts."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.core.auth.deps import require_admin
from app.models.user import User

router = APIRouter(prefix="/evaluation", tags=["evaluation"])
_BATCH_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_JOB_ID = re.compile(r"^[a-f0-9]{24}$")
_job_lock = threading.Lock()
_running_job_id: str | None = None


class EvaluationRequest(BaseModel):
    use_judge: bool = False


def _batch_root() -> Path:
    return (settings.artifacts_dir / "eval" / "batches").resolve()


def _job_root() -> Path:
    return (settings.artifacts_dir / "eval" / "score_jobs").resolve()


def _run_root() -> Path:
    return (settings.artifacts_dir / "eval" / "runs").resolve()


def _job_path(job_id: str) -> Path:
    if not _JOB_ID.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Benchmark job not found")
    root = _job_root()
    path = (root / f"{job_id}.json").resolve()
    if path.parent != root:
        raise HTTPException(status_code=404, detail="Benchmark job not found")
    return path


def _read_job(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_job(job: dict[str, Any]) -> None:
    root = _job_root()
    root.mkdir(parents=True, exist_ok=True)
    path = _job_path(str(job["job_id"]))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    path = _job_path(job_id)
    job = _read_job(path)
    if job is None:
        raise RuntimeError("Benchmark status could not be read")
    job.update(updates)
    job["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _write_job(job)
    return job


def _resolve_run(run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=404, detail="Saved evaluation run not found")
    root = _run_root()
    folder = (root / run_id).resolve()
    if folder.parent != root or not folder.is_dir() or _read_manifest(folder) is None:
        raise HTTPException(status_code=404, detail="Saved evaluation run not found")
    return folder


def _run_evaluation(job_id: str, run_id: str, use_judge: bool) -> None:
    """Score an existing immutable run bundle; this task never starts generation."""
    global _running_job_id
    path = _job_path(job_id)
    log_path = path.with_suffix(".log")
    try:
        bundle = _resolve_run(run_id)
        run_manifest = _read_manifest(bundle) or {}
        _update_job(
            job_id,
            status="running",
            phase="scoring",
            message=f"Scoring saved run {run_id} with deterministic checks" + (" and Gemini." if use_judge else "."),
        )
        scorer = Path("/srv/scripts/evaluate_batch.py")
        score_command = [sys.executable, str(scorer), str(bundle)]
        if use_judge:
            score_command.append("--judge")
        batch_root = _batch_root()
        before = {entry.name for entry in batch_root.iterdir() if entry.is_dir()} if batch_root.is_dir() else set()
        with log_path.open("a", encoding="utf-8") as log:
            scored = subprocess.run(score_command, cwd="/srv", stdout=log, stderr=subprocess.STDOUT, timeout=2 * 60 * 60)
        if scored.returncode != 0:
            raise RuntimeError("Scoring failed; check the judge configuration and review API logs.")

        created_batches = [
            _read_manifest(folder) for folder in batch_root.iterdir()
            if folder.is_dir() and folder.name not in before and (folder / "manifest.json").is_file()
        ] if batch_root.is_dir() else []
        batch = next((item for item in created_batches if item and any(run.get("run_id") == run_id for run in item.get("input_runs", []))), None)
        if batch is None:
            raise RuntimeError("Scoring completed without creating a batch report.")
        _update_job(
            job_id,
            status="completed",
            phase="completed",
            message="Benchmark complete. The report is ready below.",
            batch_id=batch.get("batch_id"),
            completed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
    except subprocess.TimeoutExpired:
        _update_job(job_id, status="failed", phase="failed", message="Benchmark timed out. Review API logs before retrying.")
    except Exception as exc:
        # Keep subprocess output and provider errors out of the API response.
        message = str(exc) if isinstance(exc, RuntimeError) else "Benchmark failed unexpectedly. Review API logs before retrying."
        _update_job(job_id, status="failed", phase="failed", message=message)
    finally:
        with _job_lock:
            if _running_job_id == job_id:
                _running_job_id = None


def _read_manifest(folder: Path) -> dict[str, Any] | None:
    path = folder / "manifest.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_batch(batch_id: str) -> Path:
    if not _BATCH_ID.fullmatch(batch_id):
        raise HTTPException(status_code=404, detail="Evaluation batch not found")
    root = _batch_root()
    folder = (root / batch_id).resolve()
    if folder.parent != root or not folder.is_dir() or _read_manifest(folder) is None:
        raise HTTPException(status_code=404, detail="Evaluation batch not found")
    return folder


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
        return rows
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation artifact {path.name} could not be read") from exc


@router.get("/judge-config")
def get_judge_config(_: User = Depends(require_admin)) -> dict[str, Any]:
    configured = bool(settings.judge_base_url.strip() and settings.judge_api_key.strip() and settings.judge_model.strip())
    return {"judge_configured": configured, "judge_model": settings.judge_model if configured else None}


@router.get("/runs")
def list_runs(_: User = Depends(require_admin)) -> list[dict[str, Any]]:
    root = _run_root()
    if not root.is_dir():
        return []
    runs = []
    for folder in sorted(root.iterdir(), key=lambda item: item.name, reverse=True):
        try:
            resolved = folder.resolve()
        except OSError:
            continue
        manifest = _read_manifest(folder) if folder.is_dir() and resolved.parent == root else None
        if manifest is None:
            continue
        course_path = folder / "course.json"
        try:
            course = json.loads(course_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            course = {}
        runs.append({
            "run_id": manifest.get("run_id") or folder.name,
            "captured_at": manifest.get("captured_at", ""),
            "data_classification": manifest.get("data_classification", "unknown"),
            "generator": manifest.get("generator") if isinstance(manifest.get("generator"), dict) else {},
            "source_names": [item.get("name", "unknown") for item in manifest.get("sources", []) if isinstance(item, dict)],
            "lesson_count": len(course.get("lessons", [])) if isinstance(course, dict) else 0,
        })
    return runs


@router.get("/jobs/status")
def get_evaluation_status(_: User = Depends(require_admin)) -> dict[str, Any]:
    root = _job_root()
    if not root.is_dir():
        return {"job": None}
    if _running_job_id:
        active = _read_job(_job_path(_running_job_id))
        if active is not None:
            return {"job": active}
    jobs = sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    latest = _read_job(jobs[0]) if jobs else None
    if latest and latest.get("status") in {"queued", "running"}:
        latest = _update_job(
            str(latest.get("job_id", "")),
            status="failed",
            phase="failed",
            message="The API restarted during this evaluation. Start scoring again to retry.",
        )
    return {"job": latest}


@router.post("/runs/{run_id}/evaluate", status_code=status.HTTP_202_ACCEPTED)
def evaluate_run(
    run_id: str,
    request: EvaluationRequest,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_admin),
) -> dict[str, Any]:
    configured = bool(settings.judge_base_url.strip() and settings.judge_api_key.strip() and settings.judge_model.strip())
    bundle = _resolve_run(run_id)
    manifest = _read_manifest(bundle) or {}
    if request.use_judge and not configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure JUDGE_BASE_URL, JUDGE_API_KEY, and JUDGE_MODEL, then recreate the API container.",
        )
    if request.use_judge and manifest.get("data_classification") not in {"public", "fictional"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gemini judging is limited to runs classified as public or fictional.",
        )
    global _running_job_id
    with _job_lock:
        if _running_job_id is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An evaluation is already running.")
        job_id = uuid.uuid4().hex[:24]
        now = datetime.now(UTC).isoformat(timespec="seconds")
        job = {
            "job_id": job_id,
            "status": "queued",
            "phase": "queued",
            "message": f"Queued saved run {run_id} for evaluation.",
            "use_judge": request.use_judge,
            "judge_model": settings.judge_model if request.use_judge else None,
            "created_at": now,
            "updated_at": now,
            "run_id": run_id,
            "batch_id": None,
            "completed_at": None,
        }
        _write_job(job)
        _running_job_id = job_id
    background_tasks.add_task(_run_evaluation, job_id, run_id, request.use_judge)
    return job


@router.get("/batches")
def list_batches(_: User = Depends(require_admin)) -> list[dict[str, Any]]:
    root = _batch_root()
    if not root.is_dir():
        return []
    batches = []
    for folder in sorted(root.iterdir(), key=lambda item: item.name, reverse=True):
        try:
            resolved = folder.resolve()
        except OSError:
            continue
        if not folder.is_dir() or resolved.parent != root:
            continue
        manifest = _read_manifest(folder)
        if manifest is None:
            continue
        batches.append({**manifest, "batch_id": manifest.get("batch_id") or folder.name})
    return batches


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, _: User = Depends(require_admin)) -> dict[str, Any]:
    folder = _resolve_batch(batch_id)
    manifest = _read_manifest(folder)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Evaluation batch not found")
    summary_path = folder / "summary.md"
    try:
        summary = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else ""
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Evaluation summary could not be read") from exc
    return {
        "manifest": manifest,
        "scores": _read_jsonl(folder / "scores.jsonl"),
        "courses": _read_jsonl(folder / "courses.jsonl"),
        "summary_markdown": summary,
    }
