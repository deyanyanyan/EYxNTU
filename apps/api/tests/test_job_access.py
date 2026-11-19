"""Job endpoints follow the project's access rule (app/routers/jobs.py)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import jobs as jobs_router

OWNER = SimpleNamespace(id="u-owner", role="instructor", is_active=True)
OTHER = SimpleNamespace(id="u-other", role="instructor", is_active=True)
ADMIN = SimpleNamespace(id="u-admin", role="admin", is_active=True)
LEARNER = SimpleNamespace(id="u-learner", role="learner", is_active=True)


class _FakeDB:
    def __init__(self, objects):
        self.objects = objects

    def get(self, model, key):
        return self.objects.get((model.__name__, key))


@pytest.fixture
def db():
    return _FakeDB({
        ("Job", "j1"): SimpleNamespace(id="j1", project_id="p1"),
        ("Job", "j0"): SimpleNamespace(id="j0", project_id=None),
        ("Project", "p1"): SimpleNamespace(id="p1", owner_id=OWNER.id),
    })


def _status(fn):
    try:
        fn()
    except HTTPException as exc:
        return exc.status_code
    return 200


@pytest.mark.parametrize("actor, read, cancel", [
    (OWNER, 200, 200),
    (ADMIN, 200, 200),
    (OTHER, 200, 403),      # instructors may read other projects but not change them
    (LEARNER, 403, 403),
])
def test_project_jobs(db, actor, read, cancel):
    assert _status(lambda: jobs_router._job(db, actor, "j1")) == read
    assert _status(lambda: jobs_router._job(db, actor, "j1", write=True)) == cancel


def test_jobs_without_a_project_and_missing_jobs(db):
    assert _status(lambda: jobs_router._job(db, OTHER, "j0")) == 200
    assert _status(lambda: jobs_router._job(db, OTHER, "j0", write=True)) == 403
    assert _status(lambda: jobs_router._job(db, ADMIN, "j0", write=True)) == 200
    assert _status(lambda: jobs_router._job(db, LEARNER, "j0")) == 403
    assert _status(lambda: jobs_router._job(db, OWNER, "nope")) == 404
