from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    target_audience: str | None = None
    duration_minutes: int | None = None
    learning_goals: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_audience: str | None = None
    duration_minutes: int | None = None
    learning_goals: str | None = None


class SourceOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None = None
    page_count: int | None = None
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str
    target_audience: str | None
    duration_minutes: int | None
    learning_goals: str | None
    created_at: datetime
    updated_at: datetime
    sources: list[SourceOut] = []

    model_config = {"from_attributes": True}
