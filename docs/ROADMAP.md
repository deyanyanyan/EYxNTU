# Project roadmap

Scope authority: the revised [project brief](project-brief.html), dated 11 September 2026. The project runs for 15 weeks, 7 September to 18 December. Use pretrained local models, retrieval, structured generation, bounded critique/revision and human approval. Training, QLoRA adapters and fine-tuning are not deliverables.

The [current two-week plan](SPRINT_01.md) defines the immediate commitments. Later dates below are targets, not claims that the features exist.

| Milestone | Target | Exit criteria |
|---|---|---|
| Foundation | 7-18 Sep | Docker setup and private credentials; auth/projects; tested startup; all teammates onboarded |
| Grounded sources | 14 Sep-2 Oct | PDF/DOCX/PPTX parsing, source inspection, stable citations, retrieval baseline over 30 questions |
| Planning and review | 28 Sep-16 Oct | Brief, objectives, syllabus, coverage map, instructor approval; persisted workflow state and resume |
| Lesson authoring | 12 Oct-6 Nov | Slides/notes/quiz/tutorial JSON, source validation, bounded critique/revision, instructor editing; mid-project demo |
| Video and LMS export | 2-20 Nov | Editable PPTX/HTML, approved narration, captioned video and SCORM 1.2 checked in two players |
| Workflow evaluation | Baselines now; comparisons 9 Nov-4 Dec | Same model/corpus across single-pass, fixed revision and agentic workflows; quality, reviewer effort, latency/calls and memory |
| Hardening and handover | 30 Nov-18 Dec | Sample course, integration tests, offline deployment evidence, evaluation report and final demonstration |

## Implementation status

Implemented code: authentication and roles; project management; upload and ingestion queue; document parsers; chunking; BGE-M3 embeddings and pgvector retrieval; source inspector; prompt versions; quiz/critique helpers.

Scaffolded or pending: planning, approval APIs, LangGraph state and interrupts, lesson orchestration, citation enforcement across assets, content editors, rendering, packaging, benchmark runner. Only ingestion currently has a working worker handler.

## Workstreams

- A owns parsing, source metadata, retrieval, citations and retrieval evaluation.
- B owns planning, coverage, workflow state and instructor review.
- C owns lesson generation, editing, approved asset formats and LMS packaging.
- D owns local serving, narration/video and workflow evaluation.
- Everyone owns tests, docs, integration and human quality review.

Keep the API for requests, PostgreSQL for application data and queued jobs, and the worker for long-running work. Introduce agent orchestration inside the worker. Define how a job yields at an approval pause and resumes from a saved checkpoint; do not keep a worker blocked while waiting for a person.

## Scope boundaries

The default development target is a local CPU setup. GPU access accelerates later experiments but does not block interface, ingestion or schema work. Validate the actual model/server pair before committing to a model size.

SCORM 2004, avatars, multilingual output, advanced analytics and enterprise SSO are optional follow-ups. Rendering stays deterministic; model decisions are limited to evidence retrieval, content drafting and revision.

## Risks to resolve early

| Risk | Next action |
|---|---|
| New-clone setup differs by machine | Collect a four-machine startup matrix and pin tested dependencies |
| Citation references can be invalid or lost on re-ingestion | Validate against the exact chunk; add source versions or protective guards |
| Project/job permissions are inconsistent | Agree the policy and add negative API tests |
| Agent calls fail or are slow on laptops | Measure structured output/tool calling early; keep a fixed workflow baseline |
| Approval cannot survive restarts | Specify checkpoint, revision and resume semantics before integrating the editor |
| Offline caches are incomplete | Rehearse with networking disabled and report parser fallbacks |