"""Editable PowerPoint export using python-pptx's default template.

Built on placeholder layouts rather than free-floating text boxes so an
instructor can restyle the whole deck from the slide master. Citation markers
stay on the slides and each lesson ends with a Sources slide that resolves them.
"""
from __future__ import annotations

import io

from pptx import Presentation
from pptx.util import Inches, Pt

from app.core.export.course import ExportCourse, ExportLesson, source_label, strip_markers, used_reference_numbers

_TITLE = 0          # Title Slide
_CONTENT = 1        # Title and Content
_TITLE_ONLY = 5     # Title Only
_MAX_TABLE_ROWS = 8


def _bullets(slide, lines: list[str]) -> None:
    body = slide.placeholders[1].text_frame
    body.clear()
    for i, line in enumerate(lines or [""]):
        para = body.paragraphs[0] if i == 0 else body.add_paragraph()
        para.text = line


def _notes(slide, text: str) -> None:
    if text:
        slide.notes_slide.notes_text_frame.text = text


def _table_slide(prs: Presentation, s: dict) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[_TITLE_ONLY])
    slide.shapes.title.text = s.get("title", "")
    rows = [r for r in (s.get("table") or []) if r][:_MAX_TABLE_ROWS]
    cols = max(len(r) for r in rows)
    top = Inches(1.6)
    shape = slide.shapes.add_table(len(rows), cols, Inches(0.5), top, prs.slide_width - Inches(1.0), Inches(0.4) * len(rows))
    for r, row in enumerate(rows):
        for c in range(cols):
            cell = shape.table.cell(r, c)
            cell.text = row[c] if c < len(row) else ""
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(12)
    bullets = s.get("bullets") or []
    if bullets:
        box = slide.shapes.add_textbox(Inches(0.5), top + Inches(0.45) * len(rows) + Inches(0.2), prs.slide_width - Inches(1.0), Inches(1.5))
        box.text_frame.word_wrap = True
        for i, line in enumerate(bullets):
            para = box.text_frame.paragraphs[0] if i == 0 else box.text_frame.add_paragraph()
            para.text = f"• {line}"
            para.font.size = Pt(14)
    _notes(slide, s.get("notes", ""))


def _lesson(prs: Presentation, lesson: ExportLesson) -> None:
    opener = prs.slides.add_slide(prs.slide_layouts[_TITLE])
    opener.shapes.title.text = lesson.title
    subtitle = lesson.module_title + (f" · {lesson.estimated_minutes} min" if lesson.estimated_minutes else "")
    opener.placeholders[1].text = subtitle

    for s in lesson.slides:
        if s.get("layout") == "title":
            # The lesson opener already carries the title; keep the model's notes on it.
            _notes(opener, s.get("notes", ""))
            continue
        if any(s.get("table") or []):  # a table of only empty rows falls through to bullets
            _table_slide(prs, s)
            continue
        slide = prs.slides.add_slide(prs.slide_layouts[_CONTENT])
        slide.shapes.title.text = s.get("title", "")
        _bullets(slide, s.get("bullets") or [])
        _notes(slide, s.get("notes", ""))

    if lesson.questions:
        slide = prs.slides.add_slide(prs.slide_layouts[_CONTENT])
        slide.shapes.title.text = "Check your understanding"
        _bullets(slide, [strip_markers(q["stem"]) for q in lesson.questions])
        answers = [f"{i}. {q['options'][q['answer_index']]} — {strip_markers(q.get('explanation', ''))}" for i, q in enumerate(lesson.questions, 1)]
        _notes(slide, "Answers\n" + "\n".join(answers))

    used = used_reference_numbers(lesson.slides)
    if used:
        slide = prs.slides.add_slide(prs.slide_layouts[_CONTENT])
        slide.shapes.title.text = "Sources"
        _bullets(slide, [f"[{n}] {source_label(lesson.references[n])}" for n in used if n in lesson.references])


def build_pptx(course: ExportCourse) -> bytes:
    prs = Presentation()

    cover = prs.slides.add_slide(prs.slide_layouts[_TITLE])
    cover.shapes.title.text = course.title
    cover.placeholders[1].text = course.summary[:300]

    if course.objectives:
        slide = prs.slides.add_slide(prs.slide_layouts[_CONTENT])
        slide.shapes.title.text = "Learning objectives"
        _bullets(slide, [o["text"] for o in course.objectives])

    for lesson in course.lessons:
        if lesson.slides or lesson.questions:
            _lesson(prs, lesson)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
