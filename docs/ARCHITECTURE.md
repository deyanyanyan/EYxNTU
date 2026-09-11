# Architecture

## Goals
This document describes the target design. The implemented pipeline currently ends at source ingestion and retrieval; generation and export handlers are stubs. The revised scope uses pretrained models without training or fine-tuning. See [sprint 1](SPRINT_01.md) for the immediate deliverable.

1. **Air-gapped**: no external APIs at runtime; every model is open-source and local.
2. **Grounded**: every generated block cites a source chunk; a validator rejects citations that do not exist.
3. **Reviewable**: plan and asset approval gates before anything is rendered or packaged.
4. **Swappable models**: the LLM, embedder and TTS are behind URLs and env vars only.
5. **Reproducible**: documented Docker startup, Alembic-managed schema, and a planned deterministic render pipeline.

## System view

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  apps/web (Next.js)  — Instructor Workbench · Admin · Learner preview        │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ REST + SSE (job progress)
┌───────────────▼──────────────────────────────────────────────────────────────┐
│  apps/api (FastAPI)                                                          │
│  auth/RBAC · projects · sources · knowledge base · course plans · assets     │
│  prompt versions · jobs · export                                             │
└───┬───────────────┬──────────────────┬──────────────────┬────────────────────┘
    │ SQLAlchemy    │ jobs table       │ OpenAI-compat    │ OpenAI-compat
┌───▼─────────┐ ┌───▼─────────────┐ ┌──▼─────────────┐ ┌──▼────────────┐
│ PostgreSQL  │ │ services/worker │ │ services/      │ │ services/tts  │
│ + pgvector  │ │ ingest · plan · │ │ inference      │ │ Piper/Kokoro  │
│             │ │ generate ·      │ │ vLLM/Ollama    │ │               │
│             │ │ render · package│ │ Qwen          │ │               │
└─────────────┘ └───┬─────────────┘ └────────────────┘ └───────────────┘
                    │
              ┌─────▼──────────┐
              │ data/ volume   │  uploads · pptx · mp4 · scorm zips · model weights
              └────────────────┘
```

## Backend layering (`apps/api/app`)
```
routers/   HTTP only: parse request, check role, call core, shape response
core/      business logic, no FastAPI imports
  auth/        password hashing, JWT, role guards, object-level permissions
  llm/         OpenAI-compatible client factory, structured-output helper, local embeddings
  rag/         parser (Docling + fallbacks) → chunker → ingest → retriever (pgvector)
  jobs/        enqueue / claim (SKIP LOCKED) / progress / cancel / finish
  prompts/     active PromptVersion or file defaults; {placeholder} substitution
  generation/  critique (3 parallel rubric scores + summary), quiz (generate→validate→fix)
models/    SQLAlchemy 2.0 typed models
schemas/   Pydantic request/response DTOs
```

## Data model
- `users` (role: admin | instructor | learner, optional `org_unit`)
- `projects` → `sources` → `chunks(embedding vector, heading_path, page_start/end, element_type)`
- `course_plans(status draft→in_review→approved)` → `modules` → `lessons(source_chunk_ids)`
- `assets(kind, content JSONB, file_path, approval, critique scores)` → `citations(block_id ↔ chunk_id, quote)`
- `jobs(kind, status, payload, progress, cancel_requested)`
- `prompt_versions(task, templates JSONB, is_active)`
- `rag_config` (embedding model in use, guards against mixed indexes)
- `reviews` (comments / decisions on plans and assets)

## Pipeline
1. **Ingest** (`ingest_source` job): Docling parses layout → structure-aware chunks keep heading breadcrumb + page range; tables are kept whole → bge-m3 embeddings → pgvector HNSW index.
2. **Plan** (M2): brief + outline excerpts → objectives (Bloom verbs) → syllabus with per-lesson `reference_numbers` → coverage map → instructor approval.
3. **Generate** (M3): per lesson, retrieve top-k → structured slide/quiz/tutorial JSON with `[n]` citation markers → citation validator (marker must map to a retrieved chunk) → critique agent → up to 2 auto-revisions → instructor edits/approves.
4. **Render** (M3/M4): slide JSON → PPTX (python-pptx) → PDF/PNG (LibreOffice headless) ; script → TTS WAV ; ffmpeg muxes slides + audio + SRT subtitles → MP4.
5. **Package** (M4): HTML5 shell + `imsmanifest.xml` (SCORM 1.2) + minimal API wrapper → ZIP.
6. **Evaluate** (M5): `packages/eval` runs the pipeline over a fixed source set for each configuration and records grounding, quality, visual usability, latency and VRAM.

## Model serving
- All chat calls go through `core/llm/client.py` using the OpenAI SDK against `LLM_BASE_URL`. Structured output uses `response_format=json_object` with schema-in-prompt and validation retries; vLLM users can switch to guided decoding later without touching callers.
- Embeddings run in-process with sentence-transformers (`EMBEDDING_MODEL`, `EMBEDDING_DIM`). The vector column width is fixed at migration time; changing the model means a new migration and a re-embed.
- `services/inference/README.md` covers the default Ollama setup and the experimental pretrained vLLM configuration.

## Job execution
Postgres is the queue. The API inserts rows; workers claim jobs with `SELECT … FOR UPDATE SKIP LOCKED`. Progress and `cancel_requested` are polled between batches. The UI subscribes to `/jobs/stream/{id}` (SSE). Cancellation, re-ingestion concurrency and project permissions need further regression coverage before authoring integration.

The API runs migrations and bootstraps its admin account in one process before readiness passes. Compose waits for database health before the API and for API health before the worker/web. Both Python services use targets in `apps/api/Dockerfile` and share dependencies. The default CPU stack excludes optional TTS (`media` profile).

Planned LangGraph integration lives inside the worker. A paused review must persist its checkpoint and release the worker; an authorized approval resumes that revision. Existing job rows do not yet implement these semantics. LangChain tools can wrap retrieval and generation helpers after local tool-calling compatibility is tested.

## Security
- JWT (HS256) with role claim; server-side role guards in FastAPI; edge middleware in Next.js routes by role but never trusts the token for authorisation.
- Uploads are size-capped, filename-sanitised and stored under `DATA_DIR/uploads/<project>/`.
- No CDN, no web fonts, no telemetry (`NEXT_TELEMETRY_DISABLED=1`).

## Frontend
Single Next.js app. Route groups `(workbench)` (projects, jobs, learn) and `(admin)` (users, prompts). `middleware.ts` enforces role prefixes. Layout is a three-pane workbench: outline · canvas · inspector, with the pipeline stepper in the top bar.
