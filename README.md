# LMS Studio

Local document-to-course authoring prototype for the NTU / EY project. The current working slice is login, projects, document upload, background ingestion and source search. Course planning, approval workflows, lesson generation, video and SCORM export are upcoming work.

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

## Current implementation

| Area | Status |
|---|---|
| Authentication, projects, uploads, source inspector | Implemented; Docker smoke check included |
| PDF / DOCX / PPTX / text ingestion, BGE-M3, pgvector search | Implemented; model-dependent smoke check included |
| Quiz generation and critique | Helper code; not connected to a complete authoring workflow |
| Plans, lessons, assets, citations, reviews | Database models; workflow APIs and editors pending |
| LangGraph / LangChain agent orchestration | Planned |
| PPTX / HTML / video / SCORM export | Planned; optional TTS service skeleton exists |
| Evaluation report | Planned; baseline collection starts in sprint 1 |

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
| `apps/api` | FastAPI, models, migrations, auth, retrieval and generation helpers |
| `apps/web` | Next.js instructor workbench and admin screens |
| `services/worker` | PostgreSQL job consumer; built from the shared API Dockerfile |
| `services/tts` | Optional speech service, enabled with the `media` profile |
| `packages/prompts` | Versioned prompt templates |
| `packages/eval` | Evaluation plan and future benchmark tooling |
| `infra` | Compose configuration and database initialization |
| `scripts` | Docker setup wrappers and smoke checks |
| `data` | Local uploads, artifacts and model caches; excluded from Git |

[Onboarding and troubleshooting](docs/ONBOARDING.md) · [Environment](docs/ENVIRONMENT.md) · [Architecture](docs/ARCHITECTURE.md) · [Two-week deliverable](docs/SPRINT_01.md) · [Verification record](docs/VERIFICATION.md)