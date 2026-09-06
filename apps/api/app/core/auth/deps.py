"""FastAPI dependencies: current user and role guards."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.auth.security import decode_token
from app.db.session import get_db
from app.models.user import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if not payload or not payload.get("sub"):
        raise _credentials_exception
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise _credentials_exception
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """Usage: `user: User = Depends(require_roles(Role.ADMIN, Role.INSTRUCTOR))`."""
    allowed = {r.value for r in roles}

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires role: {', '.join(sorted(allowed))}")
        return user

    return _guard


require_admin = require_roles(Role.ADMIN)
require_instructor = require_roles(Role.ADMIN, Role.INSTRUCTOR)
require_any = get_current_user
