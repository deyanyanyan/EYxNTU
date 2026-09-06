"""Document parsing into ParsedElement lists.

Primary: Docling (PDF/DOCX/PPTX with layout, tables, headings, page numbers).
Fallback: python-docx / python-pptx / pypdf when Docling is unavailable.
Both paths return the same element shape so chunking is parser-agnostic.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.rag.chunker import ParsedElement

log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".docx", ".pptx", ".md", ".txt"}


def parse_document(path: Path) -> tuple[list[ParsedElement], dict]:
    """Return (elements, structure_summary)."""
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"unsupported file type: {ext}")
    if ext in {".md", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return _parse_markdownish(text), {"parser": "text", "pages": None}
    try:
        return _parse_with_docling(path)
    except ImportError:
        log.warning("docling not installed; using basic parser for %s", path.name)
    except Exception as exc:  # pragma: no cover - depends on docling runtime
        log.warning("docling failed on %s (%s); using basic parser", path.name, exc)
    return _parse_basic(path)


# ---------------------------------------------------------------------------
# Docling
# ---------------------------------------------------------------------------
def _parse_with_docling(path: Path) -> tuple[list[ParsedElement], dict]:
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(path))
    doc = result.document
    elements: list[ParsedElement] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    outline: list[dict] = []

    for item, level in doc.iterate_items():
        label = getattr(item, "label", "") or ""
        text = (getattr(item, "text", "") or "").strip()
        page = None
        prov = getattr(item, "prov", None)
        if prov:
            page = getattr(prov[0], "page_no", None)

        if label in ("section_header", "title"):
            hl = 1 if label == "title" else max(1, int(level))
            while stack and stack[-1][0] >= hl:
                stack.pop()
            stack.append((hl, text))
            outline.append({"level": hl, "title": text, "page": page})
            elements.append(ParsedElement(text=text, element_type="heading", page=page, heading_path=_path(stack), level=hl))
        elif label == "table":
            try:
                md = item.export_to_markdown(doc)
            except Exception:
                md = text
            elements.append(ParsedElement(text=md, element_type="table", page=page, heading_path=_path(stack)))
        elif label in ("list_item",):
            elements.append(ParsedElement(text=f"- {text}", element_type="list", page=page, heading_path=_path(stack)))
        elif label in ("caption",):
            elements.append(ParsedElement(text=text, element_type="caption", page=page, heading_path=_path(stack)))
        elif text:
            elements.append(ParsedElement(text=text, element_type="paragraph", page=page, heading_path=_path(stack)))

    pages = getattr(doc, "num_pages", None)
    pages = pages() if callable(pages) else pages
    return elements, {"parser": "docling", "pages": pages, "outline": outline}


def _path(stack: list[tuple[int, str]]) -> str:
    return " > ".join(t for _, t in stack)


# ---------------------------------------------------------------------------
# Basic fallbacks
# ---------------------------------------------------------------------------
def _parse_basic(path: Path) -> tuple[list[ParsedElement], dict]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        els = [ParsedElement(text=(p.extract_text() or ""), page=i + 1, heading_path=path.stem) for i, p in enumerate(reader.pages)]
        return [e for e in els if e.text.strip()], {"parser": "pypdf", "pages": len(reader.pages)}
    if ext == ".docx":
        import docx

        d = docx.Document(str(path))
        els: list[ParsedElement] = []
        stack: list[tuple[int, str]] = []
        for p in d.paragraphs:
            t = p.text.strip()
            if not t:
                continue
            style = (p.style.name or "").lower()
            if style.startswith("heading"):
                lvl = int("".join(ch for ch in style if ch.isdigit()) or 1)
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                stack.append((lvl, t))
                els.append(ParsedElement(text=t, element_type="heading", heading_path=_path(stack), level=lvl))
            else:
                els.append(ParsedElement(text=t, heading_path=_path(stack)))
        for tbl in d.tables:
            rows = [" | ".join(c.text.strip() for c in r.cells) for r in tbl.rows]
            els.append(ParsedElement(text="\n".join(rows), element_type="table", heading_path=_path(stack)))
        return els, {"parser": "python-docx", "pages": None}
    if ext == ".pptx":
        from pptx import Presentation

        prs = Presentation(str(path))
        els = []
        for i, slide in enumerate(prs.slides, start=1):
            title = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else f"Slide {i}"
            for shp in slide.shapes:
                if shp.has_text_frame and shp != slide.shapes.title:
                    t = shp.text_frame.text.strip()
                    if t:
                        els.append(ParsedElement(text=t, page=i, heading_path=title))
        return els, {"parser": "python-pptx", "pages": len(prs.slides)}
    raise ValueError(f"no basic parser for {ext}")


def _parse_markdownish(text: str) -> list[ParsedElement]:
    els: list[ParsedElement] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []

    def flush():
        if buf:
            els.append(ParsedElement(text="\n".join(buf).strip(), heading_path=_path(stack)))
            buf.clear()

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            lvl = len(line) - len(line.lstrip("#"))
            title = line.lstrip("#").strip()
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, title))
            els.append(ParsedElement(text=title, element_type="heading", heading_path=_path(stack), level=lvl))
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return els
