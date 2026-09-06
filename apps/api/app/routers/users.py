from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.deps import require_admin, require_instructor
from app.core.auth.permissions import can_view_user
from app.core.auth.security import hash_password
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.auth import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return [u for u in users if can_view_user(actor, u)]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role not in {r.value for r in Role}:
        raise HTTPException(status_code=400, detail=f"role must be one of {[r.value for r in Role]}")
    if db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=body.email.lower(), name=body.name, hashed_password=hash_password(body.password), role=body.role, org_unit=body.org_unit)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def deactivate_user(user_id: str, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if actor.id == user_id:
        raise HTTPException(status_code=400, detail="You cannot deactivate yourself")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
