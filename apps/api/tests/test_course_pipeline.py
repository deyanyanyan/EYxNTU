"""Deterministic parts of the single-pass course pipeline: evidence packing,
citation mapping, plan assembly and both export formats. No model, no database."""
import io
import zipfile
import xml.etree.ElementTree as ET

from pptx import Presentation

from app.core.export.course import ExportCourse, ExportLesson, strip_markers, used_reference_numbers
from app.core.export.pptx_builder import build_pptx
from app.core.export.scorm_builder import build_scorm
from app.core.generation.evidence import dedupe, extract_citations, pack, resolve_numbers
from app.core.generation.lesson.service import Deck, Slide, normalise_deck
from app.core.generation.plan import service as plan_service
from app.core.generation.plan.service import ObjectiveSet, PlannedLesson, PlannedModule, PlannedObjective, Syllabus, build_plan_records
from app.core.rag.retriever import RetrievedChunk


def _chunk(i: int, text: str = "x" * 350, source: str = "src-a") -> RetrievedChunk:
    return RetrievedChunk(chunk_id=f"c{i}", source_id=source, source_name="policy.pdf", text=text, heading_path="1 Intro", page_start=1, page_end=1, similarity=0.9)


# ---- evidence ---------------------------------------------------------------
def test_pack_keeps_order_and_stops_at_budget():
    chunks = [_chunk(i) for i in range(10)]
    packed = pack(chunks, token_budget=400)
    assert [c.chunk_id for c in packed] == ["c0", "c1", "c2"]


def test_pack_truncates_without_mutating_the_original():
    original = _chunk(1, text="word " * 400)
    packed = pack([original], token_budget=10_000, max_chars_per_chunk=100)
    assert len(packed[0].text) < 110 and packed[0].text.endswith("…")
    assert len(original.text) == 2000


def test_dedupe_keeps_first_occurrence():
    assert [c.chunk_id for c in dedupe([_chunk(1), _chunk(2)], [_chunk(2), _chunk(3)])] == ["c1", "c2", "c3"]


def test_citations_resolve_and_invalid_markers_are_counted():
    cited = extract_citations("Masks are required [1]. Gloves too [2][1]. Unknown [9].", {1: "c1", 2: "c2"})
    assert cited.chunk_ids == ["c1", "c2"]
    assert cited.invalid_numbers == [9]
    assert cited.marker_count == 4


def test_reference_number_lists_resolve():
    assert resolve_numbers([2, 7, 2], {1: "c1", 2: "c2"}) == (["c2"], [7])


# ---- plan -------------------------------------------------------------------
def _syllabus(lessons_per_module: int, modules: int = 1, refs: list[int] | None = None) -> Syllabus:
    return Syllabus(
        title="Security onboarding",
        summary="Basics.",
        modules=[
            PlannedModule(
                title=f"Module {m}",
                lessons=[PlannedLesson(title=f"L{m}.{n}", estimated_minutes=10, objective_indexes=[1, 5], reference_numbers=refs or [1]) for n in range(lessons_per_module)],
            )
            for m in range(modules)
        ],
    )


def test_plan_records_link_objectives_sources_and_coverage():
    objectives = ObjectiveSet(objectives=[PlannedObjective(text="Identify phishing", bloom_level="understand", reference_numbers=[1, 3])])
    cmap = {1: "c1", 2: "c2"}
    plan, stats = build_plan_records("p1", 1, objectives, _syllabus(2, refs=[1, 4]), cmap, {"c1": "src-a", "c2": "src-a"})

    lessons = [les for m in plan.modules for les in m.lessons]
    assert len(lessons) == 2
    assert lessons[0].objective_ids == ["O1"]           # objective 5 does not exist
    assert lessons[0].source_chunk_ids == ["c1"]        # reference 4 does not exist
    assert stats["unknown_objective_links"] == 2
    assert stats["invalid_reference_numbers"] == 1 + 2  # objective's [3] + each lesson's [4]
    assert plan.coverage == {"src-a": 0.5}              # c1 used, c2 offered but unused


def test_plan_caps_lessons_to_bound_runtime():
    objectives = ObjectiveSet(objectives=[PlannedObjective(text="Explain", bloom_level="understand")])
    plan, stats = build_plan_records("p1", 1, objectives, _syllabus(5, modules=3), {1: "c1"}, {"c1": "s"})
    assert stats["lessons"] == plan_service.MAX_LESSONS
    assert stats["lessons_dropped_over_cap"] == 15 - plan_service.MAX_LESSONS
    assert sum(len(m.lessons) for m in plan.modules) == plan_service.MAX_LESSONS


# ---- lesson ------------------------------------------------------------------
def test_deck_gets_stable_ids_and_citation_counts():
    deck = Deck(slides=[
        Slide(id="intro", layout="title", title="Phishing", notes="Welcome."),
        Slide(id="intro", layout="bullets", title="Signs", bullets=["Urgent tone [1]", "Odd sender", "Bad link [7]"]),
        Slide(id="x", layout="summary", title="Recap", bullets=["Stay alert"]),
    ])
    slides, links, stats = normalise_deck(deck, {1: "c1"})
    assert [s["id"] for s in slides] == ["s1", "s2", "s3"]
    assert links == [("s2", "c1")]
    assert stats["invalid_citation_numbers"] == [7]
    assert stats["bullets_checked"] == 3               # title and summary slides are not checked
    assert stats["bullets_without_citation"] == 1


# ---- export ------------------------------------------------------------------
REFS = {"1": {"chunk_id": "c1", "source_name": "policy.pdf", "heading_path": "2 Email", "page_start": 3, "page_end": 4}}
QUESTION = {
    "stem": "Which sign suggests phishing?",
    "options": ["Urgent tone", "A known colleague", "Correct spelling", "Internal domain"],
    "answer_index": 0,
    "explanation": "Pressure is a common tactic [1]. </script><script>alert(1)</script>",
    "source_span": "Pressure is a common tactic.",
    "chunk_id": "c1",
}


def _course() -> ExportCourse:
    return ExportCourse(
        id="plan-1",
        title="Security <onboarding> & you",
        summary="Basics.",
        objectives=[{"id": "O1", "text": "Identify phishing"}],
        lessons=[
            ExportLesson(
                module_title="Email",
                title="Spotting phishing",
                estimated_minutes=10,
                slides=[
                    {"id": "s1", "layout": "title", "title": "Spotting phishing", "bullets": [], "table": None, "notes": "Intro notes."},
                    {"id": "s2", "layout": "bullets", "title": "Signs", "bullets": ["Urgent tone [1]", "<b>bold</b> claim [9]"], "table": None, "notes": "Explain [1]."},
                    {"id": "s3", "layout": "table", "title": "Compare", "bullets": [], "table": [["Sign", "Risk"], ["Urgency", "High [1]"]], "notes": ""},
                ],
                references=REFS,
                questions=[QUESTION],
                quiz_references=REFS,
            ),
            ExportLesson(module_title="Email", title="Reporting", estimated_minutes=5, slides=[{"id": "s1", "layout": "bullets", "title": "How", "bullets": ["Use the button"], "table": None, "notes": ""}]),
            ExportLesson(module_title="Devices", title="Empty lesson", estimated_minutes=5),
        ],
    )


def test_marker_helpers():
    assert used_reference_numbers(_course().lessons[0].slides) == ["1", "9"]
    assert strip_markers("Tactic [1]. Done [12]") == "Tactic. Done"


def test_scorm_manifest_is_well_formed_and_mirrors_course_structure():
    z = zipfile.ZipFile(io.BytesIO(build_scorm(_course())))
    names = set(z.namelist())
    assert {"imsmanifest.xml", "shared/scorm.js", "shared/style.css", "lessons/lesson_01.html", "lessons/lesson_02.html"} <= names
    assert "lessons/lesson_03.html" not in names       # lesson without content is skipped

    root = ET.fromstring(z.read("imsmanifest.xml"))
    ns = {"cp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2", "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2"}
    org = root.find("cp:organizations/cp:organization", ns)
    assert org.find("cp:title", ns).text == "Security <onboarding> & you"
    modules = org.findall("cp:item", ns)
    assert [m.find("cp:title", ns).text for m in modules] == ["Email"]
    lessons = modules[0].findall("cp:item", ns)
    assert len(lessons) == 2
    assert lessons[0].find("adlcp:masteryscore", ns).text == "70"   # has a quiz
    assert lessons[1].find("adlcp:masteryscore", ns) is None         # no quiz -> completion only
    scos = [r for r in root.findall("cp:resources/cp:resource", ns) if r.get("{http://www.adlnet.org/xsd/adlcp_rootv1p2}scormtype") == "sco"]
    assert [r.get("href") for r in scos] == ["lessons/lesson_01.html", "lessons/lesson_02.html"]


def test_scorm_pages_escape_model_text_and_resolve_citations():
    page = zipfile.ZipFile(io.BytesIO(build_scorm(_course()))).read("lessons/lesson_01.html").decode()
    assert "&lt;b&gt;bold&lt;/b&gt;" in page                         # model HTML is shown, not rendered
    assert '<a href="#ref-1">[1]</a>' in page                         # known marker becomes a link
    assert "[9]" not in page                                          # unknown marker is dropped
    assert 'id="ref-1"' in page and "policy.pdf › 2 Email (p.3–4)" in page
    assert "</script><script>alert(1)" not in page                    # cannot break out of the quiz script
    assert "SCO.start(true)" in page


def test_pptx_has_expected_slides_notes_and_sources():
    prs = Presentation(io.BytesIO(build_pptx(_course())))
    titles = [s.shapes.title.text for s in prs.slides]
    assert titles == [
        "Security <onboarding> & you", "Learning objectives",
        "Spotting phishing", "Signs", "Compare", "Check your understanding", "Sources",
        "Reporting", "How",
    ]
    assert prs.slides[2].notes_slide.notes_text_frame.text == "Intro notes."   # title slide notes kept on the opener
    assert "Urgent tone" in prs.slides[5].notes_slide.notes_text_frame.text  # quiz answers live in the notes
    assert any(sh.has_table for sh in prs.slides[4].shapes)
    sources = [p.text for p in prs.slides[6].placeholders[1].text_frame.paragraphs]
    assert sources == ["[1] policy.pdf › 2 Email (p.3–4)"]                       # [9] was never a real reference
