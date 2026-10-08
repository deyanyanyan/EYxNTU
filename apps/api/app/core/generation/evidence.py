"""Evidence selection, context packing and citation extraction for generation.

Shared by the plan and lesson generators so both cite sources the same way:
the model sees numbered references `[1]..[n]`, writes those markers into its
output, and `extract_citations` maps them back to chunk ids. A marker that
points at no reference is counted, not silently dropped — the invalid-citation
rate is one of the baseline's quality numbers.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.llm.client import estimate_tokens, prompt_token_budget
from app.core.rag.retriever import RetrievedChunk
from app.models.chunk import Chunk
from app.models.source import Source, SourceStatus

# Evidence is capped well below the model's prompt budget for two reasons:
# chat_structured's repair round appends the bad reply and the validation error,
# which must still fit; and on a CPU laptop prompt processing dominates latency
# (a 13.5k-token prompt took ~177 s), so smaller contexts keep a course run in
# minutes rather than hours. Raise this on GPU.
MAX_EVIDENCE_TOKENS = 5000

# Formatted reference header per chunk: "[n] file.pdf › Section (p.3-4)".
_REFERENCE_OVERHEAD_TOKENS = 30

_MARKER = re.compile(r"\[(\d{1,3})\]")


@dataclass
class Citations:
    chunk_ids: list[str]
    invalid_numbers: list[int]
    marker_count: int


def evidence_budget(*fixed_texts: str, schema: type[BaseModel] | None = None) -> int:
    """Tokens left for references once the prompt text and output schema are counted."""
    fixed = sum(estimate_tokens(t) for t in fixed_texts)
    if schema is not None:
        # chat_structured embeds the JSON schema in the system prompt.
        fixed += estimate_tokens(json.dumps(schema.model_json_schema(), indent=2)) + 40
    available = prompt_token_budget() - fixed - 256
    return max(0, min(available, MAX_EVIDENCE_TOKENS))


def pack(chunks: list[RetrievedChunk], token_budget: int, *, max_chars_per_chunk: int | None = None) -> list[RetrievedChunk]:
    """Keep chunks in order until the next one would exceed `token_budget`.

    Truncation, when requested, happens before formatting, so anything that
    later checks verbatim quotes against the formatted context stays consistent.
    """
    out: list[RetrievedChunk] = []
    used = 0
    for c in chunks:
        text = c.text
        if max_chars_per_chunk and len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk].rsplit(" ", 1)[0] + " …"
        cost = estimate_tokens(text) + _REFERENCE_OVERHEAD_TOKENS
        if used + cost > token_budget:
            break
        out.append(replace(c, text=text) if text is not c.text else c)
        used += cost
    return out


def dedupe(*groups: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: set[str] = set()
    out: list[RetrievedChunk] = []
    for group in groups:
        for c in group:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                out.append(c)
    return out


def extract_citations(text: str, cmap: dict[int, str]) -> Citations:
    """Resolve `[n]` markers in `text` against the reference map."""
    numbers = [int(m) for m in _MARKER.findall(text)]
    valid: list[str] = []
    invalid: list[int] = []
    for n in numbers:
        chunk_id = cmap.get(n)
        if chunk_id is None:
            invalid.append(n)
        elif chunk_id not in valid:
            valid.append(chunk_id)
    return Citations(chunk_ids=valid, invalid_numbers=invalid, marker_count=len(numbers))


def resolve_numbers(numbers: list[int], cmap: dict[int, str]) -> tuple[list[str], list[int]]:
    """Map reference numbers the model returned as a list (not inline markers)."""
    valid = [cmap[n] for n in dict.fromkeys(numbers) if n in cmap]
    invalid = [n for n in numbers if n not in cmap]
    return valid, invalid


def reference_table(chunks: list[RetrievedChunk]) -> dict[str, dict]:
    """What each `[n]` in a generated asset pointed at, stored alongside it.

    Exports need this to print a sources list; the numbering is local to the
    context the asset was generated from, so it cannot be reconstructed later.
    """
    return {
        str(i): {
            "chunk_id": c.chunk_id,
            "source_name": c.source_name,
            "heading_path": c.heading_path,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "similarity": c.similarity,
        }
        for i, c in enumerate(chunks, 1)
    }


def _to_retrieved(chunk: Chunk, filename: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        source_id=chunk.source_id,
        source_name=filename,
        text=chunk.text,
        heading_path=chunk.heading_path,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        similarity=0.0,
    )


def outline_chunks(db: Session, project_id: str) -> list[RetrievedChunk]:
    """Every ready chunk in the project, breadth first.

    Planning needs an overview of *all* the material rather than the passages
    nearest one query, so the first chunk under each distinct heading comes
    first, then the remainder in document order. Packing then keeps as much of
    that outline as the budget allows.
    """
    rows = db.execute(
        select(Chunk, Source.filename)
        .join(Source, Source.id == Chunk.source_id)
        .where(Chunk.project_id == project_id, Source.status == SourceStatus.READY.value)
        .order_by(Source.created_at, Chunk.chunk_index)
    ).all()
    heads: list[RetrievedChunk] = []
    rest: list[RetrievedChunk] = []
    seen_headings: set[tuple[str, str | None]] = set()
    for chunk, filename in rows:
        key = (chunk.source_id, chunk.heading_path)
        (rest if key in seen_headings else heads).append(_to_retrieved(chunk, filename))
        seen_headings.add(key)
    return heads + rest


def chunks_by_id(db: Session, chunk_ids: list[str]) -> list[RetrievedChunk]:
    """Load chunks in the given order; ids that no longer exist are skipped."""
    if not chunk_ids:
        return []
    rows = db.execute(
        select(Chunk, Source.filename).join(Source, Source.id == Chunk.source_id).where(Chunk.id.in_(chunk_ids))
    ).all()
    found = {chunk.id: _to_retrieved(chunk, filename) for chunk, filename in rows}
    return [found[i] for i in chunk_ids if i in found]
