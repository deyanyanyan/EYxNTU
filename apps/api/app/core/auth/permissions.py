"""Non-raising permission predicates and object-level checks."""
from __future__ import annotations

from fastapi import HTTPException, status

from app.models.project import Project
from app.models.user import Role, User


def is_admin(user: User) -> bool:
    return user.role == Role.ADMIN.value


def is_instructor(user: User) -> bool:
    return user.role in (Role.ADMIN.value, Role.INSTRUCTOR.value)


def can_view_user(actor: User, target: User) -> bool:
    """Admins see everyone; instructors see users in their org unit; users see themselves."""
    if is_admin(actor) or actor.id == target.id:
        return True
    if actor.role == Role.INSTRUCTOR.value:
        return actor.org_unit is not None and actor.org_unit == target.org_unit
    return False


def assert_project_access(actor: User, project: Project, write: bool = False) -> None:
    if is_admin(actor) or project.owner_id == actor.id:
        return
    if not write and is_instructor(actor):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this project")
