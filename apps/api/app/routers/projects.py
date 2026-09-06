from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth.deps import require_instructor
from app.core.auth.permissions import assert_project_access, is_admin
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    stmt = select(Project).options(selectinload(Project.sources)).order_by(Project.updated_at.desc())
    if not is_admin(actor):
        stmt = stmt.where(Project.owner_id == actor.id)
    return db.scalars(stmt).all()


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    p = Project(owner_id=actor.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    p = db.scalar(select(Project).options(selectinload(Project.sources)).where(Project.id == project_id))
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    assert_project_access(actor, p)
    return p


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectUpdate, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    assert_project_access(actor, p, write=True)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    assert_project_access(actor, p, write=True)
    db.delete(p)
    db.commit()
