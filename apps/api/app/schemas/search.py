from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    top_k: int | None = Field(default=None, ge=1, le=50)
    threshold: float | None = Field(default=None, ge=0, le=1)
    source_ids: list[str] | None = None


class SearchHit(BaseModel):
    chunk_id: str
    source_id: str
    source_name: str
    text: str
    heading_path: str | None
    page_start: int | None
    page_end: int | None
    similarity: float
