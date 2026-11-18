# LMS Studio: handover to EY

**NTU × EY Tech Consulting · handed over 20 November 2026**

This document is the single entry point to the codebase. It explains what the system does, how it is built, how to run it on your own machines, and what is left open. Three companion documents go deeper on specific topics and are kept in step with this one:

| Document | Read it for |
|---|---|
| [USER_FLOW.md](USER_FLOW.md) | Every screen of the web app, step by step, with UI troubleshooting |
| [MODELS.md](MODELS.md) | The trained reviewer adapters: results against their base models, how to serve them, licences |
| [services/inference/README.md](../services/inference/README.md) | Model serving in detail: Ollama context window, the vLLM GPU profile, the model bundle and its checks |

Training method and full training results are in [packages/eval/training/README.md](../packages/eval/training/README.md) and [RESULTS.md](../packages/eval/training/RESULTS.md).

---

## 1. What the system does

LMS Studio turns an organisation's own documents into a training course, then checks that course against those documents.

1. An author uploads source documents (PDF, DOCX, PPTX, Markdown, text) and writes a short brief: audience, duration, learning goals.
2. A **writer** model plans the course (objectives, modules, lessons), and after the author approves the plan, writes each lesson: slides, speaker notes and a quiz, with every bullet cited to a source passage.
3. A **reviewer** model reads each lesson next to its sources and reports what is wrong: claims the source does not support, rubric scores for depth and fit for learners, and the quality of quiz wrong answers. Its findings appear in the app on the slide or question they concern, and the author can ask the writer to fix them.
4. The author exports an editable **PowerPoint** and a **SCORM 1.2** package for an LMS.

The two models have separate jobs. The writer is a setting: a local model by default, or any OpenAI-compatible hosted model. The reviewer is the team's contribution: a 27B model fine-tuned to review course content, released in this repository as a LoRA adapter.

### Why the reviewer, not the writer, was trained

EY already has a prototype that generates courses end to end, so generation alone is not new. What a generator cannot do is tell you when it is wrong. Our benchmark (section 7) shows that a frontier writer produces richer courses but adds claims the source does not support on about two-thirds of slides. A reviewer that catches this makes any writer, local or hosted, safer to use on client material. Training a writer would also need a large set of good example courses, which we did not have; public review datasets did exist.

### Status at handover

| Area | Status |
|---|---|
| Sign-in, roles, projects, uploads, source viewer | Working |
| Ingestion: parse, chunk, embed (BGE-M3), pgvector search | Working for PDF, DOCX, PPTX, Markdown, text |
| Course plan: objectives, modules, lessons, versions, editing, approval | Working |
| Lessons: slides, notes, quizzes with citations; regenerate, edit, history, approve | Working |
| Fixing flagged content (proposed changes the author accepts or rejects) | Working, using the writer model |
| PPTX and SCORM 1.2 export; in-browser SCORM preview | Working; not yet tested in a real LMS player |
| Trained reviewer (27B LoRA) | Released and evaluated; runs as a batch job on a GPU and its findings are imported into the app |
| Live reviewer inside the running app | Code complete (`REVIEWER_ENABLED`), not yet validated on a GPU host |
| Hosted writer (e.g. Gemini Flash) | Working through configuration only; one full course generated and benchmarked |
| Automatic critique-and-revise loop, narrated video, learner publishing | Not built (stubs in the worker) |

---

## 2. Architecture

### System view

```
                          Browser (author / admin)
                                    │
                         ┌──────────▼──────────┐
                         │  web  (Next.js 15)  │  :3000
                         └──────────┬──────────┘
                                    │ REST + server-sent events (job progress)
                         ┌──────────▼──────────┐
                         │  api  (FastAPI)     │  :8000   auth · projects · sources · search
                         │                     │          course plan · lessons · export · jobs
                         └───┬─────────────┬───┘
               SQLAlchemy    │             │  jobs table (queue)
          ┌──────────────────▼──┐     ┌────▼───────────────────────┐
          │ postgres            │◄────┤ worker                     │
          │ PostgreSQL 16       │     │ ingest · plan · lessons ·  │
          │ + pgvector          │     │ revise · export            │
          └─────────────────────┘     └────┬──────────────┬────────┘
                                           │              │  OpenAI-compatible HTTP
                              data/ volume │     ┌────────▼─────────┐   ┌──────────────────┐
                    uploads · exports ·    │     │ WRITER           │   │ REVIEWER         │
                    model caches ◄─────────┘     │ ollama (cpu)     │   │ inference (gpu)  │
                                                 │  Qwen 2.5 7B     │   │  vLLM 0.32       │
                                                 │ or a hosted API  │   │  Qwen3.8-27B +   │
                                                 │  (Gemini, …)     │   │  reviewer LoRA   │
                                                 └──────────────────┘   └──────────────────┘
```

Every service runs in Docker Compose (`infra/docker-compose.yml`). Which model services start depends on `COMPOSE_PROFILES`:

| Service | Profile | Role |
|---|---|---|
| `postgres` | always | Application data, vector index and job queue |
| `api` | always | HTTP API; runs database migrations and creates the first admin on start |
| `worker` | always | Runs long jobs from the queue; includes headless LibreOffice to render Word and PowerPoint sources as PDF for the viewer |
| `web` | always | The author workbench and admin screens |
| `ollama` | `cpu` | Local writer model for laptops |
| `inference` | `gpu` | vLLM serving the 27B base model and the reviewer adapter on an NVIDIA GPU |
| `tts` | `media` | Optional speech service skeleton; not used by any feature yet |

### How a course is built

| Step | Job | Code | What happens |
|---|---|---|---|
| Ingest | `ingest_source` | `apps/api/app/core/rag/` | Docling parses layout (with simpler fallbacks), chunks keep their heading path and page range, BGE-M3 embeds them into pgvector |
| Plan | `generate_plan` | `core/generation/plan/` | An outline of all ready chunks → objectives call → syllabus call → plan with modules and lessons, each linked to source chunks. Plans are versioned; authors edit and approve them |
| Lessons | `generate_lesson_assets` | `core/generation/lesson/`, `quiz/` | Per lesson: its planned chunks plus retrieval, packed to a token budget → one deck call (slides and notes with `[n]` citations) → quiz generation with validation and repair. A failed lesson is recorded, not fatal |
| Review | batch, or live | `core/review/`, `core/llm/reviewer.py` | One request per slide (grounding), two per lesson (rubric criteria), one per quiz question (distractors). Findings are stored against the asset version they reviewed and marked stale if it changes |
| Fix | `revise_content` | `core/generation/revise.py`, `revision.py` | The writer rewrites a slide, question or lesson, given the reviewer's findings or the author's instructions. The result is a proposed change the author accepts or rejects |
| Export | `package_scorm` | `core/export/` | Deterministic, no model: editable PPTX with notes and a sources slide per lesson, and SCORM 1.2 with one SCO per lesson and a scored quiz (mastery 70) |

Citations are checked on the way in: a `[n]` marker must point at a chunk the writer was actually given, and each asset stores the reference table it was written from.

### Backend layout (`apps/api/app`)

```
routers/    HTTP only: parse the request, check the role, call core, shape the response
core/
  auth/        password hashing, JWT, role guards
  llm/         OpenAI-compatible client, context-window guard, structured output, reviewer client
  rag/         parser → chunker → ingest → retriever
  jobs/        enqueue, claim (FOR UPDATE SKIP LOCKED), progress, cancel
  prompts/     active prompt version from the database, or the file defaults in packages/prompts
  generation/  plan, lesson, quiz, evidence packing, revise
  review/      reviewer criteria, request export, findings import
  export/      PPTX and SCORM writers
models/     SQLAlchemy models   ·   schemas/  Pydantic request and response types
alembic/    database migrations (0001 initial, 0002 course revisions, 0003 chunk retirement)
```

### Data model

- `users` with role `admin`, `instructor` or `learner`
- `projects` (the course brief) → `sources` → `chunks` (embedding, heading path, pages; `retired_at` once a re-ingest replaces a chunk the course still cites)
- `course_plans` (versioned, draft → approved) → `modules` → `lessons` (linked source chunks)
- `assets` (slides, quizzes; versioned content) → `citations` (asset block ↔ chunk)
- `reviews` (approvals, reviewer findings with the reviewer's identity and prompt version)
- `jobs` (kind, status, payload, progress, cancel flag)
- `prompt_versions` (editable prompts per task; one active)
- `rag_config` (which embedding model built the index)

### Design decisions

- **Every model sits behind an OpenAI-compatible URL.** The writer, the reviewer and the hosted option are all chosen by environment variables. Swapping a model is a configuration change, never a code change.
- **PostgreSQL is the only datastore.** pgvector holds the embeddings (HNSW cosine index, always filtered by project), and the `jobs` table is the queue. There is no Redis or Celery. If throughput ever needs a broker, only `core/jobs/service.py` and the worker loop change.
- **Embeddings run inside the API and worker** with sentence-transformers on CPU. The vector width is fixed at migration time; changing the embedding model needs a migration and a re-embed, and the retriever refuses to query an index built by a different model.
- **The context window is set on both sides.** Ollama defaults to 4,096 tokens and silently drops the oldest tokens of a longer prompt, which deletes retrieved evidence without any error. Compose sets `OLLAMA_CONTEXT_LENGTH`, and the client refuses any prompt larger than `LLM_CONTEXT_TOKENS` instead of letting it be truncated.
- **Structured output** uses JSON mode with the schema in the prompt and validation retries, so it works on Ollama, vLLM and hosted APIs alike.
- **Models are data, not images.** Docker images contain code only. Base weights live in a cache under `data/models` at a revision pinned in `infra/models.lock.json`; adapters are committed through Git LFS. The inference container refuses an adapter trained on a different base model or revision.
- **Local by default.** With the `cpu` or `gpu` profile, no document leaves the machine. A hosted writer is an explicit opt-in (section 4.5).

---

## 3. Repository map

| Location | Contents |
|---|---|
| `apps/api` | FastAPI app, models, migrations, tests (`apps/api/tests`), Dockerfile shared with the worker |
| `apps/web` | Next.js app: `(workbench)` routes for projects, jobs and learner preview; `(admin)` for users and prompts |
| `services/worker` | Queue consumer and job handlers |
| `services/inference` | vLLM serving notes; the serve script is `infra/inference/serve.sh` |
| `services/tts` | Optional speech service skeleton |
| `packages/prompts` | Default prompt templates for plan, slides, quiz, critique ([README](../packages/prompts/README.md)) |
| `packages/eval/training` | `evaltrain`: reviewer data preparation, training, evaluation, batch review, served check, with results |
| `packages/eval/benchmark` | The local-against-hosted writer benchmark: data, results and grading scripts |
| `data/models/adapters` | Released reviewer adapters (weights through Git LFS) |
| `infra` | Compose files, Postgres init, model lock files |
| `scripts` | Setup and Compose wrappers, smoke checks, the course runner, the reviewer demo seed, model lock tooling |
| `.github/workflows/ci.yml` | Lint, type check and build the web app; build and start the stack; run tests, smoke and restart checks |

`data/` (uploads, artifacts, model caches) and `.env` are never committed.

---

## 4. Run it yourself

### 4.1 Prerequisites

| | Laptop (writer on CPU) | GPU host (adds the reviewer) |
|---|---|---|
| Software | Git, Docker Desktop with Linux containers (WSL2 backend on Windows), Compose 2.24+ | Linux, NVIDIA driver, Docker with GPU support, Git LFS |
| Memory | About 16 GB RAM | One 80 GB GPU (evaluated on an H200) |
| Disk | About 30 GB for images, caches and the 7B model | Plus 56 GB for the 27B base model |

No host Python, Node or Make is needed for the laptop path; everything runs in containers. The first build needs internet access for images and model downloads.

### 4.2 First start

From the repository root:

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 up --build --wait
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 exec -T api python /srv/scripts/smoke.py
```

**macOS / Linux**

```sh
sh scripts/setup.sh
sh scripts/compose.sh up --build --wait
sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py
```

`setup` writes a private `.env` from `.env.example` with a random database password, JWT secret and admin password. It never overwrites an existing `.env`. Open http://localhost:3000 and sign in with `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` from that file. API documentation is at http://localhost:8000/docs.

In the rest of this section, `sh scripts/compose.sh` stands for whichever wrapper your platform uses. On Windows, prefer the PowerShell wrapper: Git Bash rewrites container paths such as `/srv/scripts/...`.

### 4.3 Prepare the models

A healthy stack does not mean the models are downloaded. Pull the writer and run the full checks once:

```sh
sh scripts/compose.sh exec ollama ollama pull qwen2.5:7b-instruct
sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py --ingest --llm
```

`--ingest` uploads generated TXT, DOCX, PPTX and PDF files, waits for the worker and checks search; the first run downloads BGE-M3 and the Docling parser models into `data/models`. `--llm` checks that the writer returns valid structured JSON. Both clean up after themselves.

### 4.4 Generate a course

In the browser, follow [USER_FLOW.md](USER_FLOW.md): create a project, upload sources, generate and approve the outline, generate lessons, export.

From the command line, one command runs the whole pipeline on the bundled sample handbook (`scripts/fixtures/baseline_course.md`, a fictional company) and records the numbers:

```sh
sh scripts/compose.sh exec -T api python /srv/scripts/course_baseline.py --keep
```

It takes 15–30 minutes on a CPU laptop. `--keep` leaves the course in the UI; `--source <file>` (repeatable), `--audience`, `--duration` and `--goals` change the input. The record is written to `data/artifacts/baselines/<timestamp>.json`.

To see reviewer findings in the app without a GPU, seed the mock course that the trained reviewer has already reviewed:

```sh
sh scripts/compose.sh exec -T api python /srv/scripts/seed_review_demo.py
```

It creates "Northwind Information Security Essentials" with six planted errors. Import the reviewer's recorded findings for it, or review it again (section 4.6).

### 4.5 Use a hosted writer instead

Any OpenAI-compatible endpoint works. The Gemini run in section 7 used these `.env` values:

```sh
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=<your key>
LLM_MODEL=gemini-3.8-flash
LLM_CONTEXT_TOKENS=32768
LLM_MAX_TOKENS=8192
```

Then recreate the API and worker: `sh scripts/compose.sh up -d api worker`. Source passages are sent to the provider with every request, so use a hosted writer only where the client's data policy allows it. The `ollama` service can stay running or be removed from `COMPOSE_PROFILES`.

### 4.6 Run the trained reviewer

The reviewer needs one 80 GB GPU. There are two ways to use it.

**Batch (verified).** Export review requests from the app, score them on any GPU machine, and import the findings:

```sh
# 1. inside the app stack
sh scripts/compose.sh exec -T api python -m app.core.review export --project <project-id> --out /data/artifacts/review/<project-id>/requests.jsonl

# 2. on the GPU machine: vLLM 0.32.0 and this repository's evaltrain package
git lfs pull --include="data/models/adapters/reviewer-main-27b-v1/**" --exclude=""
pip install -e packages/eval/training
python -m evaltrain.review_batch --adapter-dir data/models/adapters/reviewer-main-27b-v1 \
    --requests requests.jsonl --out results.jsonl

# 3. back in the app stack, with results.jsonl next to requests.jsonl
sh scripts/compose.sh exec -T api python -m app.core.review import --project <project-id> --results /data/artifacts/review/<project-id>/results.jsonl
```

Findings appear on the slides and questions in the Lessons tab. Findings for content edited since the export are marked stale.

**Live (code complete, not yet validated on a GPU host).** On a Linux GPU host, set `COMPOSE_PROFILES=cpu,gpu`, download the base model at the pinned revision, verify the bundle, start the stack, and run the release gate before enabling the reviewer:

```sh
HF_HOME=data/models/hf hf download Qwen/Qwen3.8-27B --revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0
make models-verify
make up
make served-check ADAPTER=reviewer-main-27b-v1 MODEL=reviewer
# only if it passes: REVIEWER_ENABLED=true in .env, then make up
```

[MODELS.md](MODELS.md) and the [inference notes](../services/inference/README.md) explain each step and the prompt contract the adapter depends on.

To rehearse the batch round trip without a GPU, `review_batch --backend openai --base-url <url> --served-model <model>` sends the same prompts to any OpenAI-compatible model. Its findings are labelled with that model's name and say nothing about the trained reviewer's accuracy.

---

## 5. Configuration

All settings live in the root `.env`, generated from `.env.example`, which documents every variable inline. The ones you are most likely to change:

| Setting | Default | Purpose |
|---|---|---|
| `COMPOSE_PROFILES` | `cpu` | `cpu` starts Ollama; `cpu,gpu` adds vLLM for the reviewer; add `media` for TTS |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Ollama, `qwen2.5:7b-instruct` | The writer endpoint (section 4.5 for hosted) |
| `LLM_CONTEXT_TOKENS`, `OLLAMA_CONTEXT_LENGTH` | `16384` | Keep equal; the client refuses prompts larger than this rather than letting the server truncate |
| `LLM_MAX_TOKENS`, `LLM_TIMEOUT_SECONDS` | `4096`, `300` | Reply budget and timeout; CPU generation is slow |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `BAAI/bge-m3`, `1024` | Changing these needs a migration and re-embedding |
| `EMBEDDING_BATCH_SIZE` | `32` | Lower it if ingestion runs out of memory |
| `RAG_TOP_K`, `RAG_SIMILARITY_THRESHOLD` | `6`, `0.45` | Retrieval breadth and cut-off; not yet calibrated on a labelled set |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | `1500`, `300` | Characters per chunk |
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | `0` | Set to `1` after models are cached to forbid downloads |
| `MAX_UPLOAD_MB` | `200` | Upload size limit |
| `API_PORT`, `WEB_PORT`, `POSTGRES_PORT` | `8000`, `3000`, `5432` | Host ports, bound to localhost only |
| `NEXT_PUBLIC_API_URL`, `CORS_ORIGINS` | `http://localhost:8000`, `http://localhost:3000` | Change together with the ports; the web image must be rebuilt |
| `VLLM_MODEL`, `VLLM_REVISION`, `VLLM_LORA_MODULES` | Qwen3.8-27B at the pinned revision, `reviewer=reviewer-main-27b-v1` | What the `gpu` profile serves |
| `REVIEWER_ENABLED`, `REVIEWER_BASE_URL`, `REVIEWER_MODEL` | `false`, the `inference` service, `reviewer` | The live reviewer, separate from the writer |
| `REVIEWER_CONTEXT_TOKENS`, `REVIEWER_ENABLE_THINKING` | `8192`, `false` | Must match how the adapter was trained; leave as is |

Database and account passwords are stored in the database on first start. Regenerating `.env` does not change them, so keep the original file.

---

## 6. Day-to-day operation

```sh
sh scripts/compose.sh up --build --wait          # start or update (applies migrations)
sh scripts/compose.sh ps
sh scripts/compose.sh logs --tail=100 api worker
sh scripts/compose.sh exec -T api python -m pytest -q
sh scripts/compose.sh exec -T api ruff check . --select F
sh scripts/compose.sh stop                       # or down; both keep the data
```

- **Never run `down -v`** unless you mean to delete the database volume.
- **Code changes need a rebuild.** The API and worker run the code baked into their images: `up -d --build api worker` after Python changes. The web build runs lint and type checks, so `build web` is the frontend compile test.
- **Hot reload for development:** `docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.dev.yml up --build`. The worker does not reload; restart it after changes.
- **Restart persistence check:** `smoke.py --save-restart`, restart `postgres api worker`, then `smoke.py --verify-restart`.
- **Prompts** can be edited in the app (Admin → Prompts) as new versions; the files in `packages/prompts` are the defaults.
- **Dependencies are pinned:** `apps/api/constraints.txt`, `apps/web/package-lock.json`, and image digests in Compose. Update deliberately and rerun the checks.
- **Before committing,** run `make scrub` (secrets and identifier scan). CI runs the same checks on every pull request.

### Troubleshooting

| Symptom | Action |
|---|---|
| Docker pipe or daemon unavailable | Start Docker Desktop and wait for the Linux engine |
| Port already allocated | Change the port in `.env`; update `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` with it and rebuild `web` |
| Database authentication fails | `.env` was regenerated; restore the original database credentials |
| UI loads but API calls fail | Check `NEXT_PUBLIC_API_URL`, then rebuild `web` (the URL is fixed at build time) |
| Source or job stays queued | `logs worker`; the worker starts only after the API is healthy |
| Model not found or connection refused | Pull the exact `LLM_MODEL` name; check the profile and `logs ollama` |
| "Prompt is ~N tokens but only M fit" | The context guard working: raise both context settings together, or use fewer or shorter sources |
| Out of memory | Give Docker more memory, lower `EMBEDDING_BATCH_SIZE`, or use a smaller writer |
| First ingestion is slow | Model downloads on first use; watch `logs worker` |

UI-level problems are covered in [USER_FLOW.md](USER_FLOW.md#status-errors-and-troubleshooting).

---

## 7. Evidence

### The trained reviewer

Held-out public test sets; "base" is the same model without the adapter. Full detail in [MODELS.md](MODELS.md).

| Task | Measure | Base 27B | Trained 27B |
|---|---|---|---|
| Spot unsupported claims | Response-level F1, higher is better | 0.650 | **0.862** |
| Score lessons on a rubric | Pearson r with reference scores, higher is better | 0.778 | **0.864** |
| Rate quiz wrong answers | Mean absolute error (1–5), lower is better | 1.82 | **1.02** |

On a mock course with six planted errors (for example "12 characters" where the handbook says 14, and "within 24 hours" where it says 1 hour), the reviewer caught all six and flagged none of the clean slides ([review record](../packages/eval/training/results/review-demo/README.md)). Gemini Pro, given the same prompts, agreed on 7 of 9 slides; its two extra flags were teaching instructions, not factual claims.

### Local writer against a hosted writer

Same sample handbook, same brief, same pipeline. Both courses were graded by Gemini Pro using the reviewer's prompts, because the 27B needs a GPU that was not available for this run.

| Measure | Qwen 2.5 7B (local, CPU) | Gemini 3.8 Flash (hosted) |
|---|---|---|
| Time to generate | 27 min | 7.4 min |
| Slides / total words | 39 / 1,450 | 36 / 4,562 |
| Bullets with citations | 84% | 100% |
| Quiz questions kept after validation | 12 of 18 | 18 of 18 |
| Lesson depth / fit for learners (1–5) | 2.0 / 3.5 | 4.8 / 4.8 |
| Slides with an unsupported claim | 18% | 64% |
| Slides largely repeating another lesson | 41% | 25% |

The hosted writer teaches better but goes beyond the source, mostly with plausible extra explanation in speaker notes. The local writer stays close to the source but is shallow and repetitive. Neither writes strong quiz wrong answers. This is why the reviewer matters whichever writer is used.

The review requests, the judge's answers and the grading scripts are in [packages/eval/benchmark](../packages/eval/benchmark/README.md). `run.sh` there repeats the grading with any OpenAI-compatible judge, for example an independent one.

### Limits of this evidence

- One run per writer, on one fictional source document; no human ratings of the generated courses.
- The stand-in grader is from the same model family as one writer (though it was harder on that writer).
- Reviewer scores measure agreement with public benchmark labels. Rubric and distractor scores are advisory, not right-or-wrong checks.

---

## 8. Known issues and open work

**Known defects**

| Issue | Where | Effect |
|---|---|---|
| Quiz evidence check does not normalise quote marks | `core/generation/quiz/service.py` | A correct question quoting `'Report'` where the source has `"Report"` is rejected |
| Deleting a source deletes its citations | `Source` → `Chunk` → `Citation` cascade | Intended: the UI lists the lessons that use the source and asks first. Re-ingesting no longer has this effect (below) |
| Changed passages are not yet marked in the UI | `CitationOut.source_changed` | The API reports when a citation's passage is no longer in the re-ingested source; the lesson viewer does not show it yet |

**Fixed for handover (18 Nov 2026)**

- **Re-ingesting a source kept deleting the course's citations.** Old chunks are now retired instead of deleted (`chunks.retired_at`, migration `0003`). Afterwards [`core/rag/carry_over.py`](../apps/api/app/core/rag/carry_over.py) moves every reference to an unchanged passage onto its new chunk. It also keeps retired passages the course still cites, so their citations still show what the content was written from. Retrieval and planning ignore retired chunks.
- **Job endpoints ignored project access.** Reading, streaming and cancelling a job now follow the project rule: admins and the owner have full access, other instructors can read, and learners have none. The stream endpoint also rejects deactivated accounts.

**Not yet verified**

- The SCORM package in a real LMS player (SCORM Cloud or Moodle); it has only been played in the built-in preview.
- The live reviewer path (`REVIEWER_ENABLED=true`) on a GPU host.
- A fully offline run with networking disabled.
- Fresh-clone setup on Apple Silicon.

**Suggested next steps**

1. Validate the live reviewer on a GPU host with `make served-check`, then turn it on.
2. Close the loop: let the reviewer's findings trigger the writer's fix automatically, with a bounded number of rounds and the author's approval. The job kind `critique_asset` is reserved for this in `services/worker/handlers.py`.
3. Run a larger local writer on the GPU to narrow the depth gap without sending data out.
4. Use reviewer scores as the training signal for a local writer.
5. Collect instructor ratings on real courses to calibrate the advisory scores.

---

## 9. Security and data handling

- Passwords are hashed; sessions use HS256 JWTs with a role claim, and every API route checks the role on the server. The web middleware routes by role but never trusts the token for authorisation.
- Uploads are size-capped, renamed safely and stored under `data/uploads/<project>/`.
- Host ports bind to localhost only. Next.js telemetry is disabled, and the web app loads no CDN assets or remote fonts.
- With the default profiles, documents and generated content never leave the machine. A hosted writer sends source passages to its provider.
- The base models are Apache-2.0. The reviewer's training data licences (MIT, CC BY 4.0, Open Government Licence) are listed in [MODELS.md](MODELS.md#licences).
