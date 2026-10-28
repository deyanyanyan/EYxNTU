from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    # Spans the trained reviewer flagged on the lesson's slides; None until it has been reviewed.
    reviewer_flags: int | None = None
    # Questions the reviewer scored as having easy-to-rule-out wrong options.
    weak_questions: int = 0
    approved: bool = False  # its current slides and quiz are approved
    proposals: int = 0  # proposed changes waiting for the author


class ModuleOut(BaseModel):
    id: str
    position: int
    title: str
    description: str | None
    lessons: list[LessonSummary]


class NewSourceOut(BaseModel):
    id: str
    filename: str
    ready_at: datetime


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
    # Ready sources added or re-ingested after this plan and its lessons were generated.
    new_sources: list[NewSourceOut] = []
    meta: dict | None = None  # why this version exists: instructions, or the edits that created it
    latest: bool = True  # False when an older version is being viewed


class PlanVersionOut(BaseModel):
    id: str
    version: int
    status: str
    title: str
    created_at: datetime
    meta: dict | None
    lessons: int


class OutlineChangeOut(BaseModel):
    kind: Literal["added", "removed", "renamed", "moved"]
    what: str
    detail: str


class OutlineEdit(BaseModel):
    """One direct edit to the outline. Editing an approved outline creates a new draft version."""

    op: Literal["rename_course", "rename_module", "rename_lesson", "move_lesson", "add_lesson", "remove_lesson"]
    title: str | None = None
    lesson_id: str | None = None
    module_id: str | None = None
    delta: int = 1  # move_lesson: -1 up, +1 down


class Steering(BaseModel):
    """What steers a regeneration: free-text instructions and one-tap intents."""

    instructions: str | None = Field(default=None, max_length=2000)
    intents: list[Literal["simpler", "examples", "shorter", "fix"]] = []


class LessonsRequest(Steering):
    lesson_ids: list[str] = []  # empty: every lesson of the approved plan


class ReviseTarget(BaseModel):
    lesson_id: str
    kind: Literal["slide", "question"]
    block: str  # a slide id ("s2") or a question position ("0")


class ReviseRequest(Steering):
    """Proposed changes for chosen slides and questions, or, with ``fix``, for everything flagged in ``lesson_ids``."""

    targets: list[ReviseTarget] = []
    lesson_ids: list[str] = []
    fix: bool = False


class ProposalDecision(BaseModel):
    ids: list[str] | None = None  # None: every waiting proposal


class BlockEdit(BaseModel):
    kind: Literal["slide", "question"]
    block: str
    value: dict


class RestoreRequest(BaseModel):
    asset_id: str


class AssetVersionOut(BaseModel):
    asset_id: str
    kind: str
    version: int
    created_at: datetime
    current: bool
    approval: str
    note: str
    instructions: str | None


class AssetOut(BaseModel):
    id: str
    kind: str
    version: int
    approval: str
    content: dict | None
    # Review results, e.g. {"reviewer": {...}} from the trained reviewer (app/core/review).
    critique: dict | None = None
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


class ScormItemOut(BaseModel):
    """One node of the package's organization tree; ``href`` is None for a grouping item."""

    id: str
    title: str
    href: str | None
    mastery_score: float | None
    launch_data: str = ""
    children: list["ScormItemOut"] = []


class PreviewOut(BaseModel):
    """A preview session: the package outline and where its files are served."""

    title: str
    items: list[ScormItemOut]
    base_path: str  # /scorm-preview/<token>/ on the API; package paths resolve against it
    expires_at: datetime
    export: ExportOut
