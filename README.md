# LMS Studio

Local document-to-course authoring prototype for the NTU / EY project. A single-pass baseline runs end to end: upload documents, generate a course plan, approve it, generate a slide deck and quiz per lesson with source citations, and export an editable PPTX plus a SCORM 1.2 package. The current evaluation milestone is an offline batch benchmark over saved runs; it reports quality and failure patterns without changing generation or approval.

The revised scope uses pretrained models and agentic workflows; training and fine-tuning are not deliverables. See [scope and roadmap](docs/ROADMAP.md) and [the next two weeks](docs/SPRINT_01.md).

## Start on a teammate's laptop

Install Git and Docker Desktop with **Linux containers** (Docker Engine + Compose v2 on Linux). Start Docker first. An internet connection is needed for the first image builds and model downloads. No host Python, Node, Make or GPU is required.

Clone the GitHub repository, enter its root folder, then run:

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

Open http://localhost:3000. Read `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` in your generated `.env` to sign in. Every teammate gets independent local credentials and data. API docs: http://localhost:8000/docs.

The first startup verifies the application foundation. For document search and model calls, complete [model preparation and ingestion checks](docs/ONBOARDING.md#prepare-models-and-check-document-search). A healthy application does not mean model weights are already cached.

To run the whole pipeline once and record baseline numbers (15-30 minutes on a CPU laptop; add `--keep` to open the result in the web UI):

```sh
sh scripts/compose.sh exec -T api python /srv/scripts/course_baseline.py --keep
```

The record is written to `data/artifacts/baselines/<timestamp>.json`.

## Using the app

Sign in, create a project with a course brief, and upload sources. Then open the project's **Course** tab and work through three steps: generate and approve a plan, generate lessons, and export. The stepper in the top bar tracks Ingest → Plan → Generate → Export. The [UI user flow](docs/USER_FLOW.md) walks through every screen, what each status means, and how to fix common problems.

## Current implementation

| Area | Status |
|---|---|
| Authentication, projects, uploads, source inspector | Implemented; Docker smoke check included |
| PDF / DOCX / PPTX / text ingestion, BGE-M3, pgvector search | Implemented; model-dependent smoke check included |
| Course plan: objectives, modules, lessons, source links | Single-pass baseline; plan approval is a status change |
| Lesson decks with speaker notes and validated quizzes, with citations | Single-pass baseline; no critique or revision yet |
| PPTX and SCORM 1.2 export | Implemented; not yet checked in a real LMS player |
| Baseline runner (`scripts/course_baseline.py`) | Implemented; records per-step counts, citation quality, model calls and time |
| Offline batch evaluation | Capture/scoring commands and a read-only admin report viewer added; first four-lesson Gemini-scored batch reviewed as an exploratory baseline. See `packages/eval/README.md` |
| In-loop critique, evaluation gates, bounded revision | Future workflow experiments; not part of the current benchmark |
| LangGraph / LangChain agent orchestration | Planned |
| Narrated video | Planned; optional TTS service skeleton exists |
| Asset review and editing in the UI | Planned; assets are read-only |

### First baseline run

Recorded on 21 September 2026 on one CPU laptop, with the fictional Northwind handbook fixture and a 30-minute brief (`data/artifacts/baselines/20260921-154627.json`):

| Measure | Result |
|---|---|
| Wall clock | 27 min: ingest 20 s, plan 3 min, lessons 23.5 min, export 0.2 s |
| Plan | 6 objectives, 6 modules of 1 lesson each, every lesson linked to a source |
| Lessons | 6 decks, 39 slides, 0 failed steps |
| Citations | 43 of 51 content bullets cited (84%), 0 broken citations |
| Quiz | 12 of 18 questions kept after validation |

Facts checked against the source were accurate. The main weakness is topic bleed: the same topics repeat across lessons, which citation counts do not catch. See [the handoff notes](docs/HANDOFF.md) for the full review.

### Verification status

- 32 API tests pass, including 12 for the course pipeline; `ruff check --select F` is clean.
- The web image build (lint, TypeScript, production build) passes.
- The full pipeline ran end to end against the live model through `course_baseline.py`.
- **Not yet verified:** clicking through the Course tab in a browser, the SCORM package in an LMS player, and PDF or PPTX sources through generation.

## Team workflow

1. Pull changes and create a feature branch.
2. Run startup and smoke checks. Keep existing `.env` and Docker volumes.
3. Develop one small change; include relevant tests and update docs.
4. Open a PR with a problem statement, resulting behavior and verification results.
5. One teammate reviews it; merge after CI passes. Integrate and demo each Friday.

GitHub carries source and configuration templates. Each teammate builds locally. Never commit `.env`, uploaded documents, generated courses or model weights.

## Repository map

| Location | Purpose |
|---|---|
| `apps/api` | FastAPI, models, migrations, auth, retrieval, course planning, lesson generation and export |
| `apps/web` | Next.js instructor workbench (Sources and Course tabs) and admin screens |
| `services/worker` | PostgreSQL job consumer; built from the shared API Dockerfile |
| `services/tts` | Optional speech service, enabled with the `media` profile |
| `packages/prompts` | Versioned prompt templates |
| `packages/eval` | Evaluation plan and future benchmark tooling |
| `infra` | Compose configuration and database initialization |
| `scripts` | Docker setup wrappers, smoke checks, and the baseline runner with its fixture |
| `data` | Local uploads, artifacts and model caches; excluded from Git |

[UI user flow](docs/USER_FLOW.md) · [Onboarding and troubleshooting](docs/ONBOARDING.md) · [Environment](docs/ENVIRONMENT.md) · [Architecture](docs/ARCHITECTURE.md) · [Two-week deliverable](docs/SPRINT_01.md) · [Verification record](docs/VERIFICATION.md)
