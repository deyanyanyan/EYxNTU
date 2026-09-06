"""Background worker.

Polls the `jobs` table, claims one pending job at a time (SKIP LOCKED, so you can
run several replicas), dispatches to a handler by `kind`, and records progress,
success, failure or cancellation. Handlers live in `handlers.py` and import the
API's core package, so the worker image is the API image with a different CMD.
"""
from __future__ import annotations

import logging
import signal
import time
import traceback

from app.config import settings
from app.core.jobs import service as jobs
from app.db.session import session_scope
from handlers import HANDLERS

log = logging.getLogger("worker")
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("shutdown requested; finishing current job")


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def run_once() -> bool:
    with session_scope() as db:
        job = jobs.claim_next(db, list(HANDLERS.keys()))
        if not job:
            return False
        log.info("claimed %s %s", job.kind, job.id)
        handler = HANDLERS[job.kind]
        try:
            result = handler(db, job.id, dict(job.payload))
            if jobs.is_cancelled(db, job.id):
                jobs.cancel_finalize(db, job.id)
                log.info("cancelled %s", job.id)
            else:
                jobs.complete(db, job.id, result)
                log.info("completed %s", job.id)
        except Exception as exc:
            db.rollback()
            jobs.fail(db, job.id, type(exc).__name__, f"{exc}\n{traceback.format_exc()[-2000:]}")
            log.exception("failed %s", job.id)
        return True


def main() -> None:
    log.info("worker up. kinds=%s poll=%ss", list(HANDLERS), settings.worker_poll_seconds)
    last_cleanup = 0.0
    while _running:
        try:
            if time.time() - last_cleanup > 300:
                with session_scope() as db:
                    n = jobs.cleanup_stale(db, settings.worker_max_job_minutes)
                    if n:
                        log.warning("marked %s stale jobs as failed", n)
                last_cleanup = time.time()
            if not run_once():
                time.sleep(settings.worker_poll_seconds)
        except Exception:
            log.exception("worker loop error")
            time.sleep(settings.worker_poll_seconds * 2)


if __name__ == "__main__":
    main()
