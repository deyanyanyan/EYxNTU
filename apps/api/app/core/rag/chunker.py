"""Structure-aware chunking.

Input is a list of parsed *elements* (paragraph / heading / table / list item)
with page numbers and the heading path they sit under. Elements are grouped
under their heading path and then split with a recursive character splitter so
every chunk keeps: the heading breadcrumb as a prefix, page range, element type.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

log = logging.getLogger(__name__)


@dataclass
class ParsedElement:
    text: str
    element_type: str = "paragraph"  # paragraph | heading | table | list | caption
    page: int | None = None
    heading_path: str = ""  # "1 Intro > 1.2 Scope"
    level: int | None = None  # heading level if element_type == heading


@dataclass
class ChunkDraft:
    text: str
    chunk_index: int
    heading_path: str
    page_start: int | None
    page_end: int | None
    element_type: str
    meta: dict = field(default_factory=dict)


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", ", ", " "],
        length_function=len,
    )


def chunk_elements(elements: list[ParsedElement], *, min_chars: int = 40) -> list[ChunkDraft]:
    """Group consecutive elements by heading path, then split each group."""
    splitter = _splitter()
    drafts: list[ChunkDraft] = []
    idx = 0

    # group by heading path preserving order
    groups: list[tuple[str, list[ParsedElement]]] = []
    for el in elements:
        if el.element_type == "heading":
            continue  # headings are carried in heading_path of following elements
        if groups and groups[-1][0] == el.heading_path:
            groups[-1][1].append(el)
        else:
            groups.append((el.heading_path, [el]))

    for heading_path, els in groups:
        # tables are kept whole (one chunk each) so rows never get split apart
        tables = [e for e in els if e.element_type == "table"]
        prose = [e for e in els if e.element_type != "table"]

        for t in tables:
            if len(t.text.strip()) < min_chars:
                continue
            drafts.append(ChunkDraft(_with_breadcrumb(heading_path, t.text), idx, heading_path, t.page, t.page, "table"))
            idx += 1

        if prose:
            joined = "\n\n".join(e.text.strip() for e in prose if e.text.strip())
            if len(joined) < min_chars:
                continue
            pages = [e.page for e in prose if e.page is not None]
            p0, p1 = (min(pages), max(pages)) if pages else (None, None)
            for piece in splitter.split_text(joined):
                drafts.append(ChunkDraft(_with_breadcrumb(heading_path, piece), idx, heading_path, p0, p1, "paragraph"))
                idx += 1

    log.info("chunked %s elements into %s chunks", len(elements), len(drafts))
    return drafts


def chunk_plain_text(text: str, title: str = "") -> list[ChunkDraft]:
    """Fallback for sources without structure (txt/markdown)."""
    return chunk_elements([ParsedElement(text=text, heading_path=title)])


def _with_breadcrumb(heading_path: str, text: str) -> str:
    return f"[{heading_path}]\n\n{text}" if heading_path and not text.startswith(f"[{heading_path}]") else text
