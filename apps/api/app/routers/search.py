from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth.deps import require_instructor
from app.core.auth.permissions import assert_project_access
from app.core.rag.retriever import retrieve
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.search import SearchHit, SearchRequest

router = APIRouter(prefix="/projects/{project_id}/search", tags=["search"])


@router.post("", response_model=list[SearchHit])
def semantic_search(project_id: str, body: SearchRequest, actor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    assert_project_access(actor, p)
    hits = retrieve(db, project_id, body.query, top_k=body.top_k, threshold=body.threshold, source_ids=body.source_ids)
    return [SearchHit(**h.__dict__) for h in hits]
