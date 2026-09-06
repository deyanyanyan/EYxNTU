"""Prompt version management (admin) and resolution (any instructor)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.deps import require_admin, require_instructor
from app.core.prompts import service as prompts
from app.db.session import get_db
from app.models.prompt_version import PromptVersion
from app.models.user import User
from app.schemas.prompt_version import PromptSetOut, PromptVersionCreate, PromptVersionOut, PromptVersionUpdate

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _out(row: PromptVersion) -> PromptVersionOut:
    o = PromptVersionOut.model_validate(row)
    o.created_by_name = row.created_by.name if row.created_by else None
    return o


@router.get("/active/{task}", response_model=PromptSetOut)
def active_for_task(task: str, _: User = Depends(require_instructor), db: Session = Depends(get_db)):
    try:
        ps = prompts.get_active(db, task)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromptSetOut(task=ps.task, system_prompt=ps.system_prompt, templates=ps.templates, version_id=ps.version_id)


@router.get("/defaults/{task}", response_model=PromptSetOut)
def file_defaults(task: str, _: User = Depends(require_instructor)):
    try:
        ps = prompts.load_file_defaults(task)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromptSetOut(task=ps.task, system_prompt=ps.system_prompt, templates=ps.templates, version_id=None)


@router.get("", response_model=list[PromptVersionOut])
def list_versions(task: str | None = None, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(PromptVersion).order_by(PromptVersion.task, PromptVersion.created_at.desc())
    if task:
        stmt = stmt.where(PromptVersion.task == task)
    return [_out(r) for r in db.scalars(stmt)]


@router.post("", response_model=PromptVersionOut, status_code=201)
def create_version(body: PromptVersionCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(PromptVersion.id).where(PromptVersion.task == body.task, PromptVersion.name == body.name)):
        raise HTTPException(status_code=409, detail="A version with this name exists for this task")
    row = PromptVersion(created_by_id=actor.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.patch("/{version_id}", response_model=PromptVersionOut)
def update_version(version_id: str, body: PromptVersionUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(PromptVersion, version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/{version_id}/activate", response_model=PromptVersionOut)
def activate_version(version_id: str, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return _out(prompts.activate(db, version_id, actor.id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{version_id}", status_code=204)
def delete_version(version_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(PromptVersion, version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if row.is_active:
        raise HTTPException(status_code=400, detail="Deactivate (activate another version) before deleting")
    db.delete(row)
    db.commit()
