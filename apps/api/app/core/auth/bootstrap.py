"""Create the first admin account if the users table is empty."""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import settings
from app.core.auth.security import hash_password
from app.db.session import session_scope
from app.models.user import Role, User

log = logging.getLogger(__name__)


def ensure_default_admin() -> None:
    if not settings.default_admin_password:
        log.warning("DEFAULT_ADMIN_PASSWORD not set; skipping bootstrap admin")
        return
    with session_scope() as db:
        exists = db.scalar(select(User.id).limit(1))
        if exists:
            return
        db.add(
            User(
                email=settings.default_admin_email,
                name=settings.default_admin_name,
                hashed_password=hash_password(settings.default_admin_password),
                role=Role.ADMIN.value,
                org_unit="platform",
            )
        )
        log.info("bootstrap admin created: %s", settings.default_admin_email)
