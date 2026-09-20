"""Application settings.

All configuration comes from environment variables (or the root `.env`).
Required values are validated at import time so a misconfigured deployment
fails fast with a readable message instead of a stack trace deep in a request.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV) if _ROOT_ENV.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- database ----
    database_url: str = Field(..., description="SQLAlchemy DSN, e.g. postgresql+psycopg://user:pw@host:5432/db")

    # ---- auth ----
    secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    default_admin_email: str = "admin@lms.local"
    default_admin_password: str | None = None
    default_admin_name: str = "Platform Admin"

    # ---- llm ----
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "local-no-key-needed"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_timeout_seconds: int = 300
    # Context window the server is actually serving. Must match the server's own
    # setting (OLLAMA_CONTEXT_LENGTH / vLLM --max-model-len): servers truncate
    # oversized prompts silently, so the client refuses them instead.
    llm_context_tokens: int = 16384

    # ---- embeddings ----
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32

    # ---- retrieval ----
    rag_top_k: int = 6
    rag_similarity_threshold: float = 0.45
    chunk_size: int = 1500
    chunk_overlap: int = 300

    # ---- tts ----
    tts_base_url: str = "http://localhost:8880/v1"
    tts_voice: str = "en_US-lessac-medium"

    # ---- storage ----
    data_dir: Path = Path("/data")
    max_upload_mb: int = 200

    # ---- api ----
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    # ---- worker ----
    worker_poll_seconds: float = 2.0
    worker_max_job_minutes: int = 120

    @field_validator("secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, v: str) -> str:
        if "replace-me" in v or "change-me" in v:
            raise ValueError("SECRET_KEY is still a placeholder. Run `python scripts/gen_env.py`.")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:  # pragma: no cover - startup guard
        raise SystemExit(f"\n[config] invalid environment:\n{exc}\n\nSee docs/ENVIRONMENT.md\n") from exc


settings = get_settings()
