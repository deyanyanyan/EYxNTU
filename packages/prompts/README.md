# Prompt templates

File defaults for every LLM task. One folder per task; `system.md` is the system
prompt and every other `*.md` is a named template addressed by its file stem.

Placeholders use `{name}` and are substituted by `app/core/prompts/service.py`.
Braces that are not a known placeholder are left untouched, so JSON examples are safe.

Admins can override any task in the UI (Prompt Versions). The active DB version
wins; these files are the fallback and the reference for the evaluation report.

| task      | templates                              | used by                                  |
|-----------|----------------------------------------|------------------------------------------|
| critique  | grounding, coherence, pedagogy, summary | core/generation/critique/service.py      |
| quiz      | generate, fix                          | core/generation/quiz/service.py          |
| plan      | objectives, syllabus                   | worker `generate_plan` (M2)              |
| slides    | deck, notes, script                    | worker `generate_lesson_assets` (M3/M4)  |

Keep prompts domain-neutral. Domain context arrives at runtime through `{rag_context}`.
