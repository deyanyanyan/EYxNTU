# lms-platform

Air-gapped, open-source-model prototype that turns enterprise documents (PDF / DOCX / PPTX)
into grounded, reviewable course packages: learning objectives, syllabus, slides,
quizzes, tutorials, narrated video lessons, and a SCORM export.

Everything runs locally: PostgreSQL + pgvector, a FastAPI backend, a background worker,
an OpenAI-compatible LLM server (Ollama on laptops, vLLM + Qwen 32B on the H100), a
local TTS service, and one Next.js workbench with role-based views.

```
sources ─► ingest (parse · chunk · embed) ─► plan (objectives · syllabus · approve)
        ─► generate (slides · notes · quiz · tutorial · critique) ─► render (PPTX · TTS · MP4)
        ─► package (SCORM 1.2)
```

## Quick start (laptop, CPU profile)

```bash
python scripts/gen_env.py            # writes .env with fresh secrets, prints the admin password
make up                              # postgres · api · worker · web · tts · ollama
make pull-model                      # one-time: pull qwen2.5:7b-instruct into Ollama
```
Open http://localhost:3000 and sign in with `admin@lms.local` and the printed password.
API docs: http://localhost:8000/docs

GPU workstation: `python scripts/gen_env.py --profile gpu` and follow
`services/inference/README.md` to place the Qwen weights in `data/models/hf`.

## Repository map

| path | what |
|---|---|
| `apps/api` | FastAPI: auth/RBAC, projects, sources, retrieval, jobs, prompt versions. Alembic migrations. |
| `apps/web` | Next.js 15 workbench (instructor / admin / learner views). |
| `services/worker` | Claims jobs from Postgres and runs ingest/generate/render/package handlers. |
| `services/tts` | OpenAI-compatible `/v1/audio/speech` wrapper over Piper (cpu) / Kokoro (gpu). |
| `services/inference` | How the LLM is served (Ollama / vLLM). No code. |
| `packages/prompts` | Versioned, domain-neutral prompt templates (file defaults). |
| `packages/eval` | Benchmark harness for the model evaluation report. |
| `infra` | docker compose (base, dev overrides), Postgres init. |
| `docs` | Architecture, roadmap, onboarding, environment, ADRs. |
| `scripts` | `gen_env.py`, `scrub-check` (denylist scan). |
| `data` | Runtime volume: uploads, artifacts, model weights. Git-ignored. |

## Development

```bash
make dev        # hot reload for api, worker and web
make test       # api unit tests (no database needed)
make lint
make scrub      # denylist + secret scan (also runs as a pre-commit hook)
```
Install hooks once: `pip install pre-commit && pre-commit install`.

## Docs
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap and milestones](docs/ROADMAP.md)
- [Onboarding](docs/ONBOARDING.md)
- [Environment variables](docs/ENVIRONMENT.md)
- [ADRs](docs/adr)

## Security posture
- No outbound network at runtime. Model weights and fonts are vendored into `data/` and `apps/web/public/fonts`.
- `.env` is never committed; `scripts/gen_env.py` generates secrets locally.
- `scripts/scrub-check` blocks commits containing identifiers from any prior project.
