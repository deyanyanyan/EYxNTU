"""Seed a hand-written mock course for demonstrating reviewer findings in the app.

    docker compose ... exec api python /srv/scripts/seed_review_demo.py ["Project name"]

Writes a complete course without the generation models: a project with a learner brief,
the Northwind handbook fixture (scripts/fixtures/baseline_course.md) as a ready source
split into sections, an approved plan, and three lessons with slides, speaker notes,
quizzes and citations. Errors are planted on purpose, so the reviewer has real problems
to find:

* Lesson 1 (passwords and MFA): wrong minimum length, an invented 30-day rotation rule,
  SMS presented as a permanent option, and a quiz question with absurd distractors.
* Lesson 2 (incident reporting): a 24-hour deadline instead of 1 hour, "delete the
  message" against the handbook, and a false claim that self-reporters are disciplined.
* Lesson 3 (phishing): faithful to the source, as a control.

Chunk embeddings are deterministic placeholders, so semantic search over this project is
meaningless; the demo is about review, not retrieval. Re-running replaces the project of the
same name; pass a name to seed a separate copy (for example, to try destructive flows).
"""
from __future__ import annotations

import hashlib
import math
import random
import re
import shutil
import sys
from pathlib import Path

for candidate in (Path("/srv/api"), Path(__file__).resolve().parents[1] / "apps" / "api"):
    if (candidate / "app").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.models.asset import Asset, AssetKind, Citation  # noqa: E402
from app.models.chunk import Chunk  # noqa: E402
from app.models.course import CoursePlan, Lesson, Module, PlanStatus  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.source import Source, SourceStatus  # noqa: E402
from app.models.user import User  # noqa: E402

PROJECT_NAME = sys.argv[1] if len(sys.argv) > 1 else "Northwind security essentials (review demo)"
FIXTURE_CANDIDATES = (Path("/srv/scripts/fixtures/baseline_course.md"), Path(__file__).resolve().parent / "fixtures" / "baseline_course.md")
TITLE = "Northwind Analytics — Information Security Essentials"

OBJECTIVES = [
    {"id": "o1", "text": "Create, store and protect Northwind passwords and use MFA as the handbook requires", "bloom_level": "apply"},
    {"id": "o2", "text": "Report a suspected security incident through the right channel within the required time", "bloom_level": "apply"},
    {"id": "o3", "text": "Recognise the warning signs of phishing and verify suspicious requests", "bloom_level": "understand"},
]

# section number -> reference numbers used by each lesson's deck
LESSONS = [
    {
        "title": "Passwords and multi-factor authentication", "objective": "o1", "sections": ["3"],
        "slides": [
            ("Creating strong passwords", [
                "Northwind passwords must be at least 12 characters long [1]",  # planted: the handbook says 14
                "Passphrases of four or more unrelated words are recommended because they are long and easy to remember [1]",
                "Never reuse a Northwind password on any other site [1]",
            ], "Walk through building a passphrase from four unrelated words, and remind learners never to reuse it elsewhere."),
            ("Storing passwords", [
                "Store passwords only in the company password manager [1]",
                "Writing passwords on paper, in spreadsheets or in chat messages is not permitted [1]",
                "Change your password every 30 days, as Northwind policy requires [1]",  # planted: not in the handbook
            ], "Emphasise that the password manager is the only approved place to keep passwords."),
            ("Multi-factor authentication", [
                "MFA is mandatory for email, the company drive, the VPN and every client system that supports it [1]",
                "Use the authenticator app on your company phone [1]",
                "SMS codes are a fine permanent alternative if you prefer them [1]",  # planted: only a 7-day fallback
            ], "If you receive an MFA prompt you did not trigger, deny it and report it immediately: repeated unexpected prompts suggest someone already knows your password."),
        ],
        "quiz": [
            ("For how long may SMS codes be used instead of the authenticator app?",
             ["Up to 7 days while a phone is replaced", "Up to 14 days while a phone is replaced", "Up to 30 days while a phone is replaced", "Until the next quarterly access review"],
             "SMS codes are allowed only as a temporary fallback for up to 7 days while a phone is replaced."),
            ("What is the minimum length of a Northwind password?",  # planted: absurd distractors
             ["14 characters", "1 character", "There is no minimum", "A password made of emoji"],
             "Passwords for Northwind accounts must be at least 14 characters long."),
        ],
    },
    {
        "title": "Reporting security incidents", "objective": "o2", "sections": ["5", "6"],
        "slides": [
            ("What counts as an incident", [
                "An incident is any event that could compromise the confidentiality, integrity or availability of Northwind or client information [1]",
                "Examples include a lost laptop, a clicked phishing link, a misdirected email containing confidential data, or an unexpected MFA prompt [1]",
                "Lost or stolen devices must be reported as incidents [2]",
            ], "Stress that learners should report even when they are unsure: reporting quickly matters more than being certain."),
            ("How and when to report", [
                "Report every suspected incident to the Security Desk within 24 hours [1]",  # planted: the handbook says 1 hour
                "Use the 'Report a security incident' button in the service portal, or call extension 4400 out of hours [1]",
            ], "An early false alarm costs minutes, while a late report can cost the client relationship."),
            ("After you report", [
                "Delete the suspicious message straight away so that it cannot spread [1]",  # planted: the handbook says do not delete
                "Disconnect the affected device from the network if the Security Desk asks you to [1]",
                "Record what happened and when, while it is fresh [1]",
            ], "Staff who report their own mistakes receive a formal written warning, so check carefully before reporting."),  # planted
        ],
        "quiz": [
            ("Within what time must a suspected incident be reported to the Security Desk?",
             ["Within 1 hour of noticing it", "Within 4 hours of noticing it", "By the end of the working day", "Within 24 hours of noticing it"],
             "Report every suspected incident to the Security Desk within 1 hour of noticing it"),
            ("What should you do with a suspicious message after reporting it?",
             ["Keep it and do not investigate it yourself", "Delete it immediately", "Forward it to your team as a warning", "Reply to the sender to check whether it is genuine"],
             "Do not delete the suspicious message or try to investigate it yourself."),
        ],
    },
    {
        "title": "Recognising phishing", "objective": "o3", "sections": ["4"],
        "slides": [
            ("What phishing looks like", [
                "Phishing messages try to trick you into revealing credentials, paying money or opening malicious files [1]",
                "Most attacks against Northwind arrive by email, but chat and phone calls are increasingly used [1]",
            ], "Ask learners which of these channels they use most at work."),
            ("Warning signs", [
                "Urgency or pressure, such as a deadline measured in minutes or a threat to close an account [1]",
                "A sender address that differs from the display name, or a lookalike domain such as northwlnd.com [1]",
                "Requests to bypass normal process, such as paying an invoice without a purchase order [1]",
                "Unexpected attachments, especially archives, or links that ask you to sign in again [1]",
            ], "Practise spotting these warning signs with a sample invoice email."),
            ("Verify before you act", [
                "Verify any request for money or data through a second channel you already trust [1]",
                "For example, call the person on the number in the company directory [1]",
                "Never use contact details supplied in the suspicious message itself [1]",
            ], ""),
        ],
        "quiz": [
            ("Which of these is a warning sign of phishing listed in the handbook?",
             ["A sender address that differs from the display name", "An email sent during working hours", "A message written in formal English", "An email with a company signature"],
             "A sender address that differs from the display name, or a lookalike domain"),
            ("How should you verify an unexpected request to pay an invoice?",
             ["Call the person on the number in the company directory", "Call the phone number given in the email", "Reply to the email and ask whether it is genuine", "Check that the email has a signature block"],
             "calling the person on the number in the company directory"),
        ],
    },
]


def sections(text: str) -> dict[str, tuple[str, str]]:
    """Section number -> (heading, full section text), plus "0" for the preamble."""
    parts = re.split(r"(?m)^## ", text)
    out = {"0": ("Introduction", parts[0].strip())}
    for part in parts[1:]:
        heading = part.splitlines()[0].strip()
        out[heading.split()[0]] = (heading, "## " + part.strip())
    return out


def normalise(text: str) -> str:
    """Whitespace-insensitive comparison, as the quiz generator's span check does."""
    return " ".join(text.split()).lower()


def placeholder_embedding(text: str) -> list[float]:
    rnd = random.Random(int(hashlib.sha256(text.encode()).hexdigest()[:16], 16))
    v = [rnd.gauss(0, 1) for _ in range(settings.embedding_dim)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def citation_stats(slides: list[dict]) -> dict:
    marker = re.compile(r"\[(\d{1,3})\]")
    bullets = [b for s in slides if s["layout"] not in ("title", "summary") for b in s["bullets"]]
    markers = sum(len(marker.findall(" ".join([s["title"], *s["bullets"], s["notes"]]))) for s in slides)
    return {"slides": len(slides), "citation_markers": markers, "invalid_citation_numbers": [], "bullets_checked": len(bullets),
            "bullets_without_citation": sum(not marker.search(b) for b in bullets)}


def main() -> None:
    fixture = next(p for p in FIXTURE_CANDIDATES if p.exists())
    text = fixture.read_text(encoding="utf-8")
    secs = sections(text)
    with session_scope() as db:
        owner = db.scalar(select(User).order_by(User.created_at).limit(1))
        if owner is None:
            raise SystemExit("no users yet: start the API once so it creates the default admin")
        for old in db.scalars(select(Project).where(Project.name == PROJECT_NAME)):
            db.delete(old)
        db.flush()

        project = Project(
            name=PROJECT_NAME, owner_id=owner.id, duration_minutes=30,
            description="Hand-written mock course with deliberate errors, seeded to demonstrate reviewer findings.",
            target_audience="new Northwind employees and contractors with no security background",
            learning_goals="Report incidents correctly; create and store passwords and use MFA; recognise phishing",
        )
        db.add(project)
        db.flush()
        upload = settings.uploads_dir / project.id / fixture.name
        upload.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, upload)
        source = Source(project_id=project.id, filename=fixture.name, content_type="text/markdown", size_bytes=len(text.encode()),
                        storage_path=str(upload.relative_to(settings.data_dir)), status=SourceStatus.READY.value, chunk_count=len(secs))
        db.add(source)
        db.flush()
        chunks: dict[str, Chunk] = {}
        for i, (num, (heading, body)) in enumerate(sorted(secs.items(), key=lambda kv: int(kv[0]))):
            chunks[num] = Chunk(source_id=source.id, project_id=project.id, chunk_index=i, text=body, embedding=placeholder_embedding(body),
                                heading_path=f"{TITLE} > {heading}", element_type="paragraph")
            db.add(chunks[num])
        db.flush()

        objectives = [o | {"source_chunk_ids": [chunks[s].id for s in lesson["sections"]]} for o, lesson in zip(OBJECTIVES, LESSONS, strict=True)]
        plan = CoursePlan(project_id=project.id, version=1, title="Northwind Information Security Essentials", status=PlanStatus.APPROVED.value,
                          summary="Mock course for the reviewer demo: lessons 1 and 2 contain planted errors; lesson 3 is faithful to the handbook.",
                          learning_objectives=objectives)
        module = Module(position=1, title="Protecting accounts and reporting incidents", description="Passwords, MFA, incident reporting and phishing.")
        plan.modules = [module]
        db.add(plan)
        db.flush()

        for pos, spec in enumerate(LESSONS, 1):
            refs = {str(n): chunks[s] for n, s in enumerate(spec["sections"], 1)}
            references = {n: {"chunk_id": c.id, "source_name": fixture.name, "heading_path": c.heading_path, "page_start": None, "page_end": None} for n, c in refs.items()}
            lesson = Lesson(module_id=module.id, position=pos, title=spec["title"], objective_ids=[spec["objective"]], estimated_minutes=10,
                            source_chunk_ids=[c.id for c in refs.values()])
            db.add(lesson)
            db.flush()
            slides = [{"id": f"s{i}", "layout": "bullets", "title": t, "bullets": b, "table": None, "notes": n} for i, (t, b, n) in enumerate(spec["slides"], 1)]
            deck = Asset(project_id=project.id, lesson_id=lesson.id, kind=AssetKind.SLIDES.value, generated_with_model="hand-written mock course (review demo)",
                         content={"slides": slides, "references": references, "citation_stats": citation_stats(slides)})
            deck.citations = [Citation(block_id=s["id"], chunk_id=refs[n].id) for s in slides for n in sorted(set(re.findall(r"\[(\d)\]", " ".join(s["bullets"]))))]
            questions = []
            for stem, options, span in spec["quiz"]:
                chunk = next((c for c in refs.values() if normalise(span) in normalise(c.text)), None)
                if chunk is None:
                    raise SystemExit(f"quiz span is not verbatim from the lesson's sections: {span!r}")
                questions.append({"stem": stem, "options": options, "answer_index": 0, "explanation": f"The handbook says: {span} [1]",
                                  "difficulty": "easy", "source_span": span, "chunk_id": chunk.id})
            quiz = Asset(project_id=project.id, lesson_id=lesson.id, kind=AssetKind.QUIZ.value, generated_with_model="hand-written mock course (review demo)",
                         content={"questions": questions, "rejected": [], "references": references})
            quiz.citations = [Citation(block_id=f"q{i}", chunk_id=q["chunk_id"], quote=q["source_span"]) for i, q in enumerate(questions)]
            db.add_all([deck, quiz])
        db.commit()
        print(f"seeded project {project.id}: {len(LESSONS)} lessons, {sum(len(s['slides']) for s in LESSONS)} slides, {sum(len(s['quiz']) for s in LESSONS)} quiz questions")


if __name__ == "__main__":
    main()
