from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    db_ok = True
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
    except Exception:
        db_ok = False
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={"status": "ok" if db_ok else "degraded", "db": db_ok, "llm_model": settings.llm_model, "embedding_model": settings.embedding_model},
    )
