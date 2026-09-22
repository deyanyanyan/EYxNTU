# Session handoff

Working notes for whoever (or whatever) picks this up next. Not a team document —
`README.md`, `docs/ROADMAP.md` and `docs/project-brief.html` are the ones the team reads.

**Updated:** 21 September 2026 · **Last commit:** `0f389ce` on `main` (context fix, brief, roadmap, first version of this file) · **Uncommitted:** the baseline pipeline in section 2e, README, and this update.

The project owner is acting as PM, not implementer. They are comfortable with product
reasoning and delegation, less so with the code. Explain consequences, not mechanisms,
and keep implementation detail out of the way unless asked for it.

---

## 1. The most important thing to know

**Current priority, set by the owner on 21 September: a working product first, differentiation
later.** A single-pass baseline now runs end to end (section 2e). Do not start building the
evaluation layer unprompted — improve and harden the baseline until the owner says otherwise.
The positioning below still stands; it is the *next* milestone, and the baseline is the thing
it will be measured against.

**EY gave feedback that changes the project's positioning.** They already have a prototype
that turns documents into a course end to end, so generating a course is not this team's
contribution. The contribution is now the **agentic evaluation layer**: every generated step
is scored against the source evidence that produced it, returns pass / revise / escalate,
and records why.

Consequences already applied to the docs:

- Export (video, SCORM) shrinks — it is the least differentiated work and EY has it.
- Evaluation moves *before* export in the schedule, not after it.
- The evaluation report and the product claim are now the same deliverable.
- The repo's schema already anticipated this: `Asset.grounding_score` / `coherence_score` /
  `pedagogy_score` / `critique`, plus `Review`, `ApprovalState`, and prompt files in
  `packages/prompts/critique/`. Lean on what exists.

**The standing risk to keep raising:** a 7B model scoring its own output will approve it.
Three safeguards are written into the brief as deliverables — a deterministic code check under
every gate, an instructor agreement study, and the single-pass / fixed-revision / gated ablation.
Do not let score thresholds be invented; they come from a measured baseline.

---

## 2. What was done this session

### 2a. Verified the local model (no code change)

The team believed local Qwen serving was the blocking problem. It is not — it was already
working, and `docs/VERIFICATION.md` (11 Sep) reproduced exactly. Beyond that, the open
questions in ADR-001 were closed by direct probing:

| Check | Result | Time |
|---|---|---|
| Plain chat | pass | 1.1 s |
| Nested structured output (quiz schema) | pass | 28.6 s |
| Verbatim `source_span` grounding | 2/2 spans found | — |
| **Tool calling** | pass — correct function, well-formed args | 6.7 s |
| **Tool result round-trip** (multi-turn) | pass | 6.0 s |

**Tool calling works on `qwen2.5:7b-instruct` via Ollama.** Agent orchestration on the CPU
profile is viable; no GPU needed to start. Do not re-measure this — it is recorded in ADR-001.

### 2b. Fixed a silent context-truncation defect

Ollama served a 4096-token window (its default, not the 32k the architecture assumed) and
**dropped the oldest tokens with no error**. A needle at the start of a 13.5k-token prompt
vanished and the model answered confidently from what remained. Every grounding measurement
built on that would have been invalid.

Per-request `extra_body={"options": {"num_ctx": ...}}` is **ignored** by Ollama's
OpenAI-compatible endpoint. The window is server configuration.

Changes:

| File | Change |
|---|---|
| `infra/docker-compose.yml` | `OLLAMA_CONTEXT_LENGTH: ${OLLAMA_CONTEXT_LENGTH:-16384}` on the `ollama` service |
| `apps/api/app/config.py` | `llm_context_tokens: int = 16384` |
| `apps/api/app/core/llm/client.py` | `ContextOverflowError`, `estimate_tokens`, `prompt_token_budget`, `_guard_context`, `_warn_if_truncated`; guards wired into `chat_text` and `chat_structured` |
| `apps/api/tests/test_context_guard.py` | new, 9 tests |
| `.env.example`, `.env` | `OLLAMA_CONTEXT_LENGTH=16384`, `LLM_CONTEXT_TOKENS=16384` |
| `docs/ENVIRONMENT.md`, `docs/adr/001-model-serving.md`, `services/inference/README.md` | documented, incl. memory and latency costs |

Verified end-to-end after the fix:

```
evidence at ~13.5k tokens    RECALLED   'BLUEHERON-77'     (was: silently lost)
evidence at ~30k tokens      REFUSED    "Prompt is ~34738 tokens but only 16128 fit..."
```

The guard is re-checked inside `chat_structured`'s retry loop, because each repair round
appends the bad output plus the validation error and can outgrow the window mid-loop.

`prompt_token_budget()` exists so retrieval code can pack chunks to fit rather than crash —
use it when the planning and lesson agents are built.

**Backward compatible.** A teammate with an older `.env` still gets 16384 from the Compose
default and the pydantic default. `scripts/gen_env.py` copies from `.env.example`, so new
clones pick the vars up automatically.

### 2c. Rewrote the project brief around the new positioning

`docs/project-brief.html` — same four-page A4 print format and visual identity, new content.
Page 1 states where the contribution sits relative to EY's prototype, the three gate checks
(grounding / coherence / pedagogy) and the three honesty safeguards. Page 2 has the resequenced
timeline and revised A–D ownership. Both SVG diagrams were rebuilt: architecture now shows the
evaluation layer between generation and storage; the workflow diagram shows the pass / revise /
escalate gate on each step with its bounded revision loop.

`docs/ROADMAP.md` was aligned — it cites the brief as scope authority and would otherwise
contradict it. Added a "Contribution" section and two new risk rows.

### 2d. Published a handover page for the team

<https://claude.ai/artifact/38me5NaXBt5YxAfacqyzLS> — project state, dependency ladder, week-two
assignments with blank name slots, green/red flags, risk register, kickoff checklist.

**This page is now partly stale**: it predates the EY feedback, so its 15-week arc and
priorities still show export ahead of evaluation. The week-2 assignments are still correct.
Republish by passing that URL as `url` — do not create a second artifact.

### 2e. Built a single-pass baseline that runs end to end

Upload → plan → approve → lessons → export now works, through the API and a **Course** tab on the
project page. No critique, gates or revision — deliberately, so it is the baseline arm.

| Step | Where | What it does |
|---|---|---|
| Plan | `app/core/generation/plan/service.py` | Breadth-first outline of every ready chunk → objectives call → syllabus call → `CoursePlan` / `Module` / `Lesson` with source chunk links. Caps at 8 lessons. |
| Approve | `POST /projects/{id}/plan/{plan_id}/approve` | Status flip plus a `Review` row. Deliberately **not** workstream B's pause/resume design. |
| Lessons | `app/core/generation/lesson/service.py` | Per lesson: planned chunks + retrieval → one deck call (5–7 slides with notes) → existing quiz generator (3 questions, validate-and-repair). Failures are recorded per lesson, not fatal. |
| Export | `app/core/export/` | Deterministic, no model. Editable PPTX (placeholder layouts, notes, a Sources slide per lesson) and SCORM 1.2 (one SCO per lesson, grouped by module, quiz reports score against mastery 70). |
| Shared | `app/core/generation/evidence.py` | Evidence packing to a token budget (`MAX_EVIDENCE_TOKENS = 5000`), `[n]` citation extraction, reference tables stored with each asset. |
| API | `app/routers/course.py` | Enqueue plan / lessons / export (409 while one of the same kind is running), read plan and lesson detail, list and download exports. |
| UI | `apps/web/components/course-panel.tsx` | Three step cards with live job progress, per-run numbers, lesson viewer with clickable citations into the inspector, authenticated downloads. |
| Runner | `scripts/course_baseline.py` + `scripts/fixtures/baseline_course.md` | One command runs everything and writes `data/artifacts/baselines/<ts>.json`. The fixture is a deliberately fictional company handbook. |

Supporting changes: `run_blocking()` in `client.py` (the worker runs each job in a fresh event loop
and the cached async client otherwise fails with "Event loop is closed"); a real model-call counter
(`llm_call_count()`); a `{slide_count}` variable in `packages/prompts/slides/deck.md`; stepper
stages are now Ingest / Plan / Generate / Export.

**First baseline, 21 Sep, this laptop, Northwind fixture, 30-minute brief** — record
`data/artifacts/baselines/20260921-154627.json`:

| | Result |
|---|---|
| Total wall clock | 27 min (ingest 20 s · plan 3 min · lessons 23.5 min · export 0.2 s) |
| Plan | 6 objectives, 6 modules × 1 lesson, 2 model calls, 0 invalid references, every lesson linked to a source |
| Lessons | 6 decks, 39 slides, 20 model calls, 0 failed steps, 2.7–6.4 min per lesson |
| Citations | 43 of 51 content bullets cited (84%), 0 citations pointing at nothing |
| Quiz | 12 of 18 questions kept; 5 rejected as `length_giveaway`, 1 as `span_not_found` |
| Export | 53-slide PPTX, SCORM with 6 lesson pages; both open |

**What the numbers hide — found by reading every bullet against the handbook:**

- **Facts are accurate.** Every specific rule checked (14 characters, 1 hour, extension 4400,
  5-minute lock, 7-day updates, vault-only storage) matches the source. One mild mis-citation:
  "MFA adds an extra layer of security [2]" is general knowledge the source does not state.
- **Topics bleed across lessons — the biggest weakness.** Incident reporting appears in 4 of 6
  lessons; the phishing lesson has a clear-desk slide. Retrieval pulls neighbouring chunks and the
  deck prompt does not know what the other lessons cover. Citation counts cannot see this.
  Quiz questions repeat across lessons too (two near-identical MFA-prompt questions).
- **The plan is flat.** One lesson per module, i.e. one per handbook section; 35 minutes planned
  against 30 requested.
- **One quiz rejection is a validator false positive.** The model quoted the portal button name
  with single quotes where the source has double quotes, and the exact-match span check rejected
  it. Quote normalisation would fix it. Left alone so the baseline records current behaviour — a
  candidate first improvement.
- `length_giveaway` (answer > 2.5x the shortest option) rejected 5 of 18. Policy answers are
  naturally specific; unclear yet whether the threshold or the model is at fault.

The project is kept as **"Baseline 9a7072"** (`56d0c8d6-...`) so the owner can open it in the web
UI. It has two exports: the second was queued by an ad-hoc endpoint check.

---

## 3. Deliberately NOT fixed

Both were left for teammates A and C as their sprint tickets. The owner was offered them and
has not said to take them. **Ask before implementing.**

| Bug | Where | Consequence |
|---|---|---|
| Citations destroyed on re-ingestion | `apps/api/app/models/asset.py:64` — `Citation.chunk_id` is `ON DELETE CASCADE` to `chunks` | Re-upload a corrected source and every citation on already-approved assets is deleted silently. Ticket S1-04, workstream A. |
| Job endpoints ignore project membership | `apps/api/app/routers/jobs.py` — `get_job:28` checks only that a user is logged in; `stream_job:49` validates the JWT signature and nothing else | Any authenticated user can read or stream any project's jobs. Ticket S1-05, workstream C. |

---

## 4. What's next, in order

1. **Owner decisions.** Names against workstreams A–D; create the sprint tickets
   (`docs/SPRINT_01.md`); agree what Friday's demo shows now that a generated course exists.
2. **Commit the baseline pipeline.** Sections 2a–2d are in `0f389ce`; section 2e (pipeline, UI,
   runner, fixture, README, this file) is uncommitted.
3. **Owner looks at the output.** Open "Baseline 9a7072" in the web UI and the exported PPTX. The
   owner has not seen generated content yet and should judge it before the team optimises numbers.
4. **Baseline hardening** — the owner's stated priority. In rough value order:
   - Stop topic bleed: tell the deck prompt what the *other* lessons cover, and keep lesson
     evidence to its planned chunks plus retrieval that excludes other lessons' chunks.
   - Normalise quotes and whitespace in the quiz span check (`quiz/service.py:47`).
   - Check the SCORM package in a real player (SCORM Cloud or Moodle) — never done.
   - Run the baseline on a real PDF and a PPTX, not only Markdown.
   - Asset review and editing in the UI (assets are read-only; exports flag `includes_unapproved`).
5. **Record every change as a new baseline run** so improvements are measured, not asserted.
   Keep the fixture, brief and model fixed when comparing.
6. **Then** the evaluation layer from section 1. Its coherence gate would target exactly the
   topic-bleed problem the baseline exposed.

The two bugs in section 3 are still A's and C's tickets.

---

## 5. Running things (Windows host, Docker Desktop)

Docker Desktop may not be running — `"C:\Program Files\Docker\Docker\Docker Desktop.exe"`,
then wait for the engine.

```powershell
cd C:\Users\Mr-De\Downloads\lms-platform
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 up --build --wait
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 exec -T api python /srv/scripts/smoke.py --llm
```

Or drive Compose directly, which is what actually worked here:

```powershell
docker compose --env-file .env -f infra/docker-compose.yml exec -T api python -m pytest -q
docker compose --env-file .env -f infra/docker-compose.yml exec -T api ruff check . --select F
```

### Gotchas that cost time

- **Git Bash mangles container paths.** `sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py`
  becomes `/srv/api/C:/Program Files/Git/srv/...`. Use the PowerShell wrapper, or set
  `MSYS_NO_PATHCONV=1`.
- **The API container runs the baked image, not your host edits.** After changing Python, run
  `docker compose ... up -d --build api worker` or your new tests simply will not appear.
- **For ad-hoc probes**, `docker cp script.py lms-platform-api-1:/tmp/` then exec it, and delete
  it afterwards. Do not leave files in the container or the repo.
- **Model weights are already cached** in `data/models/ollama` (4.4 GB, `qwen2.5:7b-instruct`,
  ID `845dbda0ea48`). No pull needed. `ollama ps` shows empty after ~5 min idle — that is unload,
  not failure.
- **Long runs outlive the Bash tool's 10-minute cap.** Stopping `docker compose exec` does *not*
  kill the process inside the container. For the baseline runner, run it detached or watch the
  `jobs` table; the image has no `ps` — scan `/proc/*/cmdline` with Python instead.
- **`web` bakes lint and type checks into its image build**, so `docker compose ... build web` is
  the frontend compile test. It passed clean for the Course panel.
- **`.env` is gitignored and contains real credentials.** It was edited locally to add the two
  new vars. Never commit it, never print it.

### Measured on this machine (Windows, Docker 29.2.1, 20 CPU, 15.5 GiB)

- Model resident: 5.1 GB at 4k context, 5.9 GB at 16k.
- 13.5k-token prompt: 177 s, against `LLM_TIMEOUT_SECONDS=300`. Gating multiplies calls 3–4×,
  so a full gated course is hours on CPU. This is the GPU justification.

---

## 6. Verification status

- `32 passed` (11 original + 9 context guard + 12 course pipeline), `ruff check . --select F` clean.
- Web image build (Next.js lint + TypeScript + production build) passes.
- `smoke.py --llm` passed after the context fix.
- Full pipeline passed end to end via `course_baseline.py` against the live model; the lesson
  detail endpoint was exercised for all six lessons.

**Not verified:** clicking through the Course tab in a browser (it compiles and its endpoints work,
but no one has used it); the SCORM package in any LMS player; PDF or PPTX sources through
generation; `smoke.py --ingest`, restart persistence and the offline rehearsal since these changes.
`docs/VERIFICATION.md` has not been updated with this session's results.
