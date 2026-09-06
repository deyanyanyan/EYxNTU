from datetime import datetime

from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    project_id: str | None
    payload: dict
    result: dict | None
    progress_current: int
    progress_total: int
    message: str | None
    error_type: str | None
    error_message: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}
