"""SCORM 1.2 package export.

One SCO per lesson, grouped under module items so the LMS shows the course
structure. A lesson with a quiz reports a 0-100 score and passed/failed against
the mastery score; a lesson without one reports completed on open.

Known limits of this baseline: the ADL/IMS schema files (*.xsd) are not bundled
(SCORM Cloud and Moodle import without them; strict validators may not), and
quiz answers are embedded in the page, so the quiz is formative, not secure.
"""
from __future__ import annotations

import html
import io
import json
import re
import zipfile
from xml.sax.saxutils import escape, quoteattr

from app.core.export.course import ExportCourse, ExportLesson, reference_for_chunk, source_label, strip_markers, used_reference_numbers

MASTERY_SCORE = 70
_MARKER = re.compile(r"\[(\d{1,3})\]")

SCORM_JS = """\
(function () {
  function find(win) {
    var hops = 0;
    while (win && !win.API && win.parent && win.parent !== win && hops < 10) { win = win.parent; hops++; }
    return win && win.API ? win.API : null;
  }
  var api = find(window) || (window.opener ? find(window.opener) : null);
  var finished = false;
  function set(k, v) { if (api) api.LMSSetValue(k, v); }
  window.SCO = {
    connected: function () { return !!api; },
    start: function (hasQuiz) {
      if (!api) return;
      api.LMSInitialize("");
      var status = api.LMSGetValue("cmi.core.lesson_status");
      if (!hasQuiz) set("cmi.core.lesson_status", "completed");
      else if (status === "not attempted" || status === "") set("cmi.core.lesson_status", "incomplete");
      api.LMSCommit("");
    },
    score: function (raw, mastery) {
      if (!api) return;
      set("cmi.core.score.min", "0");
      set("cmi.core.score.max", "100");
      set("cmi.core.score.raw", String(raw));
      set("cmi.core.lesson_status", raw >= mastery ? "passed" : "failed");
      api.LMSCommit("");
    },
    finish: function () {
      if (!api || finished) return;
      finished = true;
      api.LMSFinish("");
    }
  };
  window.addEventListener("pagehide", window.SCO.finish);
  window.addEventListener("beforeunload", window.SCO.finish);
})();
"""

STYLE_CSS = """\
:root { --ink:#1d2430; --muted:#5b6474; --line:#dde2e8; --accent:#0e6e70; --soft:#eef5f5; --ok:#2f7d4f; --no:#a9372b; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.6 "Segoe UI", system-ui, -apple-system, sans-serif; color: var(--ink); background: #fff; }
main { max-width: 760px; margin: 0 auto; padding: 32px 20px 64px; }
header p { color: var(--muted); margin: 4px 0 0; }
h1 { font-size: 28px; line-height: 1.2; margin: 0; }
h2 { font-size: 20px; margin: 0 0 8px; }
section.slide { border-top: 1px solid var(--line); padding: 22px 0; }
section.slide ul { margin: 8px 0 12px; padding-left: 22px; }
.notes { color: var(--ink); background: var(--soft); border-radius: 6px; padding: 12px 14px; margin: 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 14px; }
th, td { border: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: var(--soft); }
sup a { color: var(--accent); text-decoration: none; font-size: 12px; }
.quiz { border-top: 2px solid var(--accent); margin-top: 28px; padding-top: 22px; }
fieldset { border: 1px solid var(--line); border-radius: 6px; margin: 0 0 14px; padding: 12px 14px; }
legend { font-weight: 600; padding: 0 4px; }
label { display: block; padding: 4px 0; cursor: pointer; }
button { background: var(--accent); color: #fff; border: 0; border-radius: 6px; padding: 10px 18px; font: inherit; font-weight: 600; cursor: pointer; }
button:focus-visible { outline: 3px solid #b07a12; outline-offset: 2px; }
.feedback { margin: 8px 0 0; font-size: 14px; }
.feedback.ok { color: var(--ok); } .feedback.no { color: var(--no); }
.source { color: var(--muted); font-size: 13px; }
#score { font-weight: 600; margin-left: 12px; }
.refs { border-top: 1px solid var(--line); margin-top: 28px; padding-top: 12px; font-size: 13px; color: var(--muted); }
.refs ol { padding-left: 22px; }
"""

QUIZ_JS = """\
document.getElementById("quiz").addEventListener("submit", function (e) {
  e.preventDefault();
  var right = 0;
  QUIZ.forEach(function (q, i) {
    var chosen = document.querySelector('input[name="q' + i + '"]:checked');
    var ok = chosen && Number(chosen.value) === q.answer;
    if (ok) right++;
    var fb = document.getElementById("fb" + i);
    fb.textContent = (ok ? "Correct. " : chosen ? "Not quite. " : "No answer. ") + q.explanation;
    fb.className = "feedback " + (ok ? "ok" : "no");
  });
  var pct = Math.round((100 * right) / QUIZ.length);
  document.getElementById("score").textContent = "Score: " + pct + "%";
  SCO.score(pct, MASTERY);
});
"""


def _with_citations(text: str, known: set[str]) -> str:
    """Escape model text, then turn known [n] markers into links to the sources list."""
    safe = html.escape(text or "")
    return _MARKER.sub(lambda m: f'<sup><a href="#ref-{m.group(1)}">[{m.group(1)}]</a></sup>' if m.group(1) in known else "", safe)


def _slide_html(s: dict, known: set[str]) -> str:
    parts = [f"<section class=\"slide\"><h2>{html.escape(s.get('title', ''))}</h2>"]
    rows = [r for r in (s.get("table") or []) if r]
    if rows:
        head, *body = rows
        parts.append("<table><thead><tr>" + "".join(f"<th>{_with_citations(c, known)}</th>" for c in head) + "</tr></thead><tbody>")
        parts.extend("<tr>" + "".join(f"<td>{_with_citations(c, known)}</td>" for c in r) + "</tr>" for r in body)
        parts.append("</tbody></table>")
    if s.get("bullets"):
        parts.append("<ul>" + "".join(f"<li>{_with_citations(b, known)}</li>" for b in s["bullets"]) + "</ul>")
    if s.get("notes"):
        parts.append(f"<p class=\"notes\">{_with_citations(s['notes'], known)}</p>")
    parts.append("</section>")
    return "".join(parts)


def _quiz_html(lesson: ExportLesson) -> tuple[str, str]:
    blocks = []
    data = []
    for i, q in enumerate(lesson.questions):
        options = "".join(
            f"<label><input type=\"radio\" name=\"q{i}\" value=\"{j}\"> {html.escape(opt)}</label>" for j, opt in enumerate(q["options"])
        )
        ref = reference_for_chunk(lesson.quiz_references, q.get("chunk_id"))
        source = f"<p class=\"source\">Source: {html.escape(source_label(ref))}</p>" if ref else ""
        blocks.append(f"<fieldset><legend>{i + 1}. {html.escape(strip_markers(q['stem']))}</legend>{options}<p id=\"fb{i}\" class=\"feedback\" aria-live=\"polite\"></p>{source}</fieldset>")
        data.append({"answer": q["answer_index"], "explanation": strip_markers(q.get("explanation", ""))})
    form = (
        "<section class=\"quiz\"><h2>Check your understanding</h2><form id=\"quiz\">"
        + "".join(blocks)
        + "<button type=\"submit\">Submit answers</button><span id=\"score\" aria-live=\"polite\"></span></form></section>"
    )
    # "</" is escaped so model text inside the JSON cannot close the script element.
    quiz_json = json.dumps(data).replace("</", "<\\/")
    script = f"var QUIZ = {quiz_json};\nvar MASTERY = {MASTERY_SCORE};\n{QUIZ_JS}"
    return form, script


def lesson_page(course: ExportCourse, lesson: ExportLesson) -> str:
    used = [n for n in used_reference_numbers(lesson.slides) if n in lesson.references]
    known = set(used)
    body = "".join(_slide_html(s, known) for s in lesson.slides if s.get("layout") != "title")
    intro = next((s.get("notes", "") for s in lesson.slides if s.get("layout") == "title"), "")
    quiz, quiz_script = _quiz_html(lesson) if lesson.questions else ("", "")
    refs = ""
    if used:
        refs = "<section class=\"refs\"><h2>Sources</h2><ol>" + "".join(
            f"<li id=\"ref-{n}\" value=\"{n}\">{html.escape(source_label(lesson.references[n]))}</li>" for n in used
        ) + "</ol></section>"
    minutes = f" · {lesson.estimated_minutes} min" if lesson.estimated_minutes else ""
    has_quiz = "true" if lesson.questions else "false"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(lesson.title)}</title>"
        "<link rel=\"stylesheet\" href=\"../shared/style.css\"><script src=\"../shared/scorm.js\"></script></head>"
        f"<body><main><header><h1>{html.escape(lesson.title)}</h1>"
        f"<p>{html.escape(course.title)} · {html.escape(lesson.module_title)}{minutes}</p></header>"
        + (f"<p class=\"notes\">{_with_citations(intro, known)}</p>" if intro else "")
        + body
        + quiz
        + refs
        + f"</main><script>SCO.start({has_quiz});\n{quiz_script}</script></body></html>\n"
    )


def manifest(course: ExportCourse, lessons: list[tuple[str, ExportLesson]]) -> str:
    items: list[str] = []
    resources: list[str] = []
    current_module: str | None = None
    module_n = 0
    for n, (href, lesson) in enumerate(lessons, 1):
        if lesson.module_title != current_module:
            if current_module is not None:
                items.append("</item>")
            module_n += 1
            current_module = lesson.module_title
            items.append(f"<item identifier=\"module_{module_n:02d}\" isvisible=\"true\"><title>{escape(lesson.module_title)}</title>")
        mastery = f"<adlcp:masteryscore>{MASTERY_SCORE}</adlcp:masteryscore>" if lesson.questions else ""
        items.append(f"<item identifier=\"item_{n:02d}\" identifierref=\"res_{n:02d}\" isvisible=\"true\"><title>{escape(lesson.title)}</title>{mastery}</item>")
        resources.append(
            f"<resource identifier=\"res_{n:02d}\" type=\"webcontent\" adlcp:scormtype=\"sco\" href={quoteattr(href)}>"
            f"<file href={quoteattr(href)}/><dependency identifierref=\"shared\"/></resource>"
        )
    if current_module is not None:
        items.append("</item>")
    resources.append(
        "<resource identifier=\"shared\" type=\"webcontent\" adlcp:scormtype=\"asset\">"
        "<file href=\"shared/scorm.js\"/><file href=\"shared/style.css\"/></resource>"
    )
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        f"<manifest identifier={quoteattr('lms-studio-' + course.id)} version=\"1.0\" "
        "xmlns=\"http://www.imsproject.org/xsd/imscp_rootv1p1p2\" "
        "xmlns:adlcp=\"http://www.adlnet.org/xsd/adlcp_rootv1p2\" "
        "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" "
        "xsi:schemaLocation=\"http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd "
        "http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd "
        "http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd\">"
        "<metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata>"
        f"<organizations default=\"org\"><organization identifier=\"org\"><title>{escape(course.title)}</title>"
        + "".join(items)
        + "</organization></organizations><resources>"
        + "".join(resources)
        + "</resources></manifest>\n"
    )


def build_scorm(course: ExportCourse) -> bytes:
    lessons = [(f"lessons/lesson_{n:02d}.html", lesson) for n, lesson in enumerate((le for le in course.lessons if le.slides or le.questions), 1)]
    if not lessons:
        raise ValueError("No lesson has generated content to package.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("imsmanifest.xml", manifest(course, lessons))
        z.writestr("shared/scorm.js", SCORM_JS)
        z.writestr("shared/style.css", STYLE_CSS)
        for href, lesson in lessons:
            z.writestr(href, lesson_page(course, lesson))
    return buf.getvalue()
