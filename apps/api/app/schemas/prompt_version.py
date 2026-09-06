from datetime import datetime

from pydantic import BaseModel


class PromptVersionCreate(BaseModel):
    task: str
    name: str
    system_prompt: str | None = None
    templates: dict[str, str] = {}
    notes: str | None = None


class PromptVersionUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    templates: dict[str, str] | None = None
    notes: str | None = None


class PromptVersionOut(BaseModel):
    id: str
    task: str
    name: str
    system_prompt: str | None
    templates: dict[str, str]
    notes: str | None
    is_active: bool
    created_by_id: str
    created_by_name: str | None = None
    last_activated_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PromptSetOut(BaseModel):
    task: str
    system_prompt: str
    templates: dict[str, str]
    version_id: str | None
