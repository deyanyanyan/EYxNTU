"""Regression checks for first-login serialization and readiness failures."""
from contextlib import contextmanager

from app.schemas.auth import UserOut
from app.routers import health


def test_existing_local_bootstrap_email_serializes():
    user = UserOut(id='admin', email='admin@lms.local', name='Admin', role='admin')
    assert user.model_dump()['email'] == 'admin@lms.local'


def test_health_returns_failure_when_database_is_unavailable(monkeypatch):
    @contextmanager
    def unavailable():
        raise ConnectionError('database unavailable')
        yield

    monkeypatch.setattr(health.engine, 'connect', unavailable)
    assert health.health().status_code == 503
