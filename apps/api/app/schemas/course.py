from datetime import datetime

from pydantic import BaseModel


class ObjectiveOut(BaseModel):
    id: str
    text: str
    bloom_level: str
    source_chunk_ids: list[str] = []


class LessonSummary(BaseModel):
    id: str
    position: int
    title: str
    estimated_minutes: int | None
    objective_ids: list[str]
    source_chunk_count: int
    slides: int
    questions: int
    generated_at: datetime | None


class ModuleOut(BaseModel):
    id: str
    position: int
    title: str
    description: str | None
    lessons: list[LessonSummary]


class PlanOut(BaseModel):
    id: str
    version: int
    title: str
    summary: str | None
    status: str
    learning_objectives: list[ObjectiveOut]
    coverage: dict[str, float] | None
    source_names: dict[str, str]
    modules: list[ModuleOut]
    created_at: datetime


class AssetOut(BaseModel):
    id: str
    kind: str
    version: int
    approval: str
    content: dict | None
    generated_with_model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CitationOut(BaseModel):
    block_id: str
    chunk_id: str
    quote: str | None
    source_name: str
    heading_path: str | None
    page_start: int | None
    page_end: int | None
    text: str


class LessonDetail(BaseModel):
    lesson: LessonSummary
    module_title: str
    slides: AssetOut | None
    quiz: AssetOut | None
    citations: list[CitationOut]


class ExportOut(BaseModel):
    id: str
    created_at: datetime
    content: dict | None

    model_config = {"from_attributes": True}
