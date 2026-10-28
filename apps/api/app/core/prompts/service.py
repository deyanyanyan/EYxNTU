"""Prompt version resolution and template substitution.

Order of precedence for a task's prompts:
  1. the active PromptVersion row for that task (editable in the admin UI)
  2. the file defaults in packages/prompts/<task>/*.md (checked into git)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prompt_version import PromptVersion


def _find_prompts_dir() -> Path:
    """Repo layout: <root>/packages/prompts. Docker layout: /srv/packages/prompts next to /srv/api."""
    import os

    if os.environ.get("PROMPTS_DIR"):
        return Path(os.environ["PROMPTS_DIR"])
    here = Path(__file__).resolve()
    for up in (5, 4):
        cand = here.parents[up] / "packages" / "prompts"
        if cand.is_dir():
            return cand
    return here.parents[5] / "packages" / "prompts"


PROMPTS_DIR = _find_prompts_dir()


@dataclass
class PromptSet:
    task: str
    system_prompt: str
    templates: dict[str, str]
    version_id: str | None  # None => file defaults

    def render(self, name: str, **vars: str) -> str:
        tpl = self.templates.get(name)
        if tpl is None:
            # A version saved in the admin UI before this template existed falls back to the file default.
            tpl = load_file_defaults(self.task).templates.get(name) if self.version_id else None
        if tpl is None:
            raise KeyError(f"prompt task '{self.task}' has no template '{name}'")
        return substitute(tpl, **vars)


def substitute(template: str, **vars: str) -> str:
    """`{name}` placeholders only; braces elsewhere are left alone (safe for JSON examples)."""
    out = template
    for k, v in vars.items():
        out = out.replace("{" + k + "}", v if v is not None else "")
    return out


def load_file_defaults(task: str) -> PromptSet:
    d = PROMPTS_DIR / task
    if not d.is_dir():
        raise FileNotFoundError(f"no default prompts for task '{task}' in {d}")
    system = (d / "system.md").read_text(encoding="utf-8") if (d / "system.md").exists() else ""
    templates = {p.stem: p.read_text(encoding="utf-8") for p in d.glob("*.md") if p.stem != "system"}
    return PromptSet(task=task, system_prompt=system, templates=templates, version_id=None)


def get_active(db: Session, task: str) -> PromptSet:
    row = db.scalar(select(PromptVersion).where(PromptVersion.task == task, PromptVersion.is_active.is_(True)))
    if row:
        return PromptSet(task=task, system_prompt=row.system_prompt or "", templates=dict(row.templates or {}), version_id=row.id)
    return load_file_defaults(task)


def get_by_id(db: Session, version_id: str) -> PromptSet | None:
    row = db.get(PromptVersion, version_id)
    if not row:
        return None
    return PromptSet(task=row.task, system_prompt=row.system_prompt or "", templates=dict(row.templates or {}), version_id=row.id)


def activate(db: Session, version_id: str, by_user_id: str) -> PromptVersion:
    from datetime import datetime

    row = db.get(PromptVersion, version_id)
    if not row:
        raise ValueError("prompt version not found")
    for other in db.scalars(select(PromptVersion).where(PromptVersion.task == row.task, PromptVersion.is_active.is_(True))):
        other.is_active = False
    row.is_active = True
    row.last_activated_at = datetime.now(UTC)
    row.last_activated_by_id = by_user_id
    db.commit()
    db.refresh(row)
    return row
