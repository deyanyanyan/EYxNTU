import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.auth.bootstrap import ensure_default_admin
from app.routers import auth, course, health, jobs, projects, prompts, scorm_preview, search, sources, users

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    ensure_default_admin()
    log.info("api ready. llm=%s @ %s, embeddings=%s", settings.llm_model, settings.llm_base_url, settings.embedding_model)
    yield


app = FastAPI(
    title="LMS Content Generation API",
    version="0.1.0",
    description="Air-gapped document-to-course pipeline. Schema is managed by Alembic; run `alembic upgrade head` before starting.",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(sources.router)
app.include_router(search.router)
app.include_router(jobs.router)
app.include_router(prompts.router)
app.include_router(course.router)
app.include_router(scorm_preview.router)
