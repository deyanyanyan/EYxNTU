"""Deterministic, descriptive checks for saved course output bundles."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

_CITATION = re.compile(r"\[(\d{1,3})\]")
_WORD = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?")
_SPACE = re.compile(r"\s+")
_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"', "‟": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
})
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on",
    "or", "that", "the", "this", "to", "was", "were", "with", "you", "your",
}
MAX_BULLETS_PER_SLIDE = 5
MAX_VISIBLE_WORDS_PER_SLIDE = 85
LOW_LEXICAL_OVERLAP = 0.2
NEAR_DUPLICATE_SIMILARITY = 0.88


def normalize_text(value: str) -> str:
    """Normalize typographic punctuation and whitespace for span diagnostics."""
    value = unicodedata.normalize("NFKC", value).translate(_QUOTE_MAP)
    return _SPACE.sub(" ", value).strip().casefold()


def _tokens(value: str) -> set[str]:
    return {word for word in _WORD.findall(normalize_text(value)) if word not in _STOPWORDS and len(word) > 1}


def _refs(lesson: dict[str, Any], asset_key: str) -> dict[str, dict[str, Any]]:
    asset = lesson.get(asset_key) or {}
    content = asset.get("content") or {}
    refs = content.get("references") or {}
    evidence = (lesson.get("evidence") or {}).get(asset_key) or {}
    combined: dict[str, dict[str, Any]] = {}
    for number, ref in refs.items():
        combined[str(number)] = {**ref, **(evidence.get(str(number)) or {})}
    for number, ref in evidence.items():
        combined.setdefault(str(number), ref)
    return combined


def _visible_slide_text(slide: dict[str, Any]) -> str:
    cells = [str(cell) for row in (slide.get("table") or []) for cell in (row or [])]
    return " ".join([str(slide.get("title") or ""), *(str(b) for b in slide.get("bullets") or []), *cells])


def evaluate_lesson(lesson: dict[str, Any]) -> dict[str, Any]:
    """Return counts and concrete findings; these are not pass/fail decisions."""
    lesson_id = (lesson.get("lesson") or {}).get("id") or lesson.get("lesson_id")
    slides_asset = lesson.get("slides") or {}
    slides_content = slides_asset.get("content") or {}
    slides = slides_content.get("slides") or []
    slide_refs = _refs(lesson, "slides")
    quiz_asset = lesson.get("quiz") or {}
    quiz_content = quiz_asset.get("content") or {}
    quiz_refs = _refs(lesson, "quiz")
    findings: list[dict[str, Any]] = []
    counts: dict[str, Any] = {
        "citations_invalid": 0,
        "citation_references_missing_text": 0,
        "bullets_checked": 0,
        "bullets_uncited": 0,
        "bullets_low_lexical_overlap": 0,
        "slides_over_density_limit": 0,
        "quiz_accepted": len(quiz_content.get("questions") or []),
        "quiz_rejected": len(quiz_content.get("rejected") or []),
        "quiz_span_not_found": 0,
        "quiz_rejections_by_code": {},
    }

    for number, ref in slide_refs.items():
        if not ref.get("text"):
            counts["citation_references_missing_text"] += 1
            findings.append({"type": "reference_text_missing", "reference": number, "chunk_id": ref.get("chunk_id")})

    for slide_index, slide in enumerate(slides, 1):
        slide_id = str(slide.get("id") or f"s{slide_index}")
        bullets = [str(b) for b in slide.get("bullets") or []]
        slide_text = " ".join([
            str(slide.get("title") or ""), *bullets,
            *(str(cell) for row in (slide.get("table") or []) for cell in (row or [])),
            str(slide.get("notes") or ""),
        ])
        invalid_slide_refs = [number for number in _CITATION.findall(slide_text) if number not in slide_refs]
        if invalid_slide_refs:
            counts["citations_invalid"] += len(invalid_slide_refs)
            findings.append({"type": "invalid_citation", "slide_id": slide_id, "numbers": invalid_slide_refs})
        if slide.get("layout") not in ("title", "summary"):
            for bullet in bullets:
                counts["bullets_checked"] += 1
                numbers = _CITATION.findall(bullet)
                if not numbers:
                    counts["bullets_uncited"] += 1
                    findings.append({"type": "uncited_bullet", "slide_id": slide_id, "text": bullet[:300]})
                    continue
                selected_refs = []
                for number in dict.fromkeys(numbers):
                    ref = slide_refs.get(number)
                    if ref is not None and ref.get("text"):
                        selected_refs.append(ref)
                if selected_refs:
                    bullet_tokens = _tokens(_CITATION.sub("", bullet))
                    evidence_tokens = set().union(*(_tokens(str(ref.get("text") or "")) for ref in selected_refs))
                    overlap = len(bullet_tokens & evidence_tokens) / max(1, len(bullet_tokens))
                    if bullet_tokens and overlap < LOW_LEXICAL_OVERLAP:
                        counts["bullets_low_lexical_overlap"] += 1
                        findings.append({
                            "type": "low_lexical_overlap",
                            "slide_id": slide_id,
                            "ratio": round(overlap, 3),
                            "text": bullet[:300],
                            "references": [
                                {
                                    "number": number,
                                    "chunk_id": ref.get("chunk_id"),
                                    "source_name": ref.get("source_name"),
                                }
                                for number in dict.fromkeys(numbers)
                                if (ref := slide_refs.get(number)) is not None
                            ],
                        })
        words = len(_WORD.findall(normalize_text(_visible_slide_text(slide))))
        if len(bullets) > MAX_BULLETS_PER_SLIDE or words > MAX_VISIBLE_WORDS_PER_SLIDE:
            counts["slides_over_density_limit"] += 1
            findings.append({"type": "slide_density", "slide_id": slide_id, "bullets": len(bullets), "visible_words": words})

    quiz_text_by_chunk: dict[str, str] = {}
    for ref in quiz_refs.values():
        if ref.get("chunk_id") and ref.get("text"):
            quiz_text_by_chunk[ref["chunk_id"]] = str(ref["text"])
    for question_index, question in enumerate(quiz_content.get("questions") or [], 1):
        source_span = str(question.get("source_span") or "")
        chunk_id = question.get("chunk_id")
        evidence_text = quiz_text_by_chunk.get(chunk_id, "")
        if not source_span or normalize_text(source_span) not in normalize_text(evidence_text):
            counts["quiz_span_not_found"] += 1
            findings.append({
                "type": "quiz_span_not_found",
                "question": question_index,
                "chunk_id": chunk_id,
                "text": source_span[:300],
            })
    for rejected in quiz_content.get("rejected") or []:
        for issue in rejected.get("issues") or []:
            code = str(issue.get("code") or "unknown")
            counts["quiz_rejections_by_code"][code] = counts["quiz_rejections_by_code"].get(code, 0) + 1

    return {"lesson_id": lesson_id, "title": (lesson.get("lesson") or {}).get("title"), "counts": counts, "findings": findings}


def evaluate_course_overlap(lessons: list[dict[str, Any]]) -> dict[str, Any]:
    """Report shared cited evidence and near-duplicate visible bullets across lessons."""
    chunk_to_lessons: dict[str, set[str]] = defaultdict(set)
    bullets: list[tuple[str, str, str]] = []
    for lesson in lessons:
        lesson_meta = lesson.get("lesson") or {}
        lesson_id = str(lesson_meta.get("id") or lesson.get("lesson_id") or "")
        for citation in lesson.get("citations") or []:
            if citation.get("chunk_id"):
                chunk_to_lessons[str(citation["chunk_id"])].add(lesson_id)
        for slide in ((lesson.get("slides") or {}).get("content") or {}).get("slides") or []:
            slide_id = str(slide.get("id") or "")
            for bullet in slide.get("bullets") or []:
                text = _CITATION.sub("", str(bullet)).strip()
                if text:
                    bullets.append((lesson_id, slide_id, text))

    shared = [
        {"chunk_id": chunk_id, "lesson_ids": sorted(ids)}
        for chunk_id, ids in chunk_to_lessons.items()
        if len(ids) > 1
    ]
    near_duplicates: list[dict[str, Any]] = []
    for index, left in enumerate(bullets):
        left_norm = normalize_text(left[2])
        if not left_norm:
            continue
        for right in bullets[index + 1 :]:
            if left[0] == right[0]:
                continue
            right_norm = normalize_text(right[2])
            similarity = SequenceMatcher(None, left_norm, right_norm).ratio()
            if similarity >= NEAR_DUPLICATE_SIMILARITY:
                near_duplicates.append({
                    "left": {"lesson_id": left[0], "slide_id": left[1], "text": left[2][:300]},
                    "right": {"lesson_id": right[0], "slide_id": right[1], "text": right[2][:300]},
                    "similarity": round(similarity, 3),
                })
    return {
        "shared_cited_chunks": len(shared),
        "shared_chunk_examples": shared[:100],
        "near_duplicate_bullet_pairs": len(near_duplicates),
        "near_duplicate_examples": near_duplicates[:100],
        "heuristic_thresholds": {
            "low_lexical_overlap_below": LOW_LEXICAL_OVERLAP,
            "near_duplicate_similarity_at_least": NEAR_DUPLICATE_SIMILARITY,
            "max_bullets_per_slide": MAX_BULLETS_PER_SLIDE,
            "max_visible_words_per_slide": MAX_VISIBLE_WORDS_PER_SLIDE,
        },
    }
