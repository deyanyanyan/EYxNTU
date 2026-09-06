# Onboarding

## 0. Prerequisites
- Docker Desktop (or Docker Engine + compose v2)
- Python 3.12 and Node 20 if you want to run services outside Docker
- ~10 GB free for the cpu profile (Ollama 7B + bge-m3); ~40 GB for the gpu profile

## 1. First run
```bash
git clone <internal-remote> lms-platform && cd lms-platform
python scripts/gen_env.py          # creates .env; note the admin password it prints
make up                            # builds and starts everything
make pull-model                    # cpu profile only, once
```
- Web: http://localhost:3000 (login `admin@lms.local`)
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

First start downloads `BAAI/bge-m3` into `data/models/hf`. After that, set
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` in `.env` for a fully offline run.

## 2. Day-to-day
```bash
make dev      # hot reload (api --reload, next dev)
make logs
make test     # apps/api unit tests, no DB required
make scrub    # must pass before every commit (pre-commit runs it too)
```
Install the hooks once: `pip install pre-commit && pre-commit install`.

## 3. Where things live
- Add an endpoint: `apps/api/app/routers/<area>.py` → call into `app/core/<area>/`. Never put business logic in a router.
- Add a background task: add a `JobKind`, a handler in `services/worker/handlers.py`, enqueue with `core/jobs/service.enqueue`.
- Change the schema: edit `app/models/*`, then `cd apps/api && alembic revision --autogenerate -m "..."`, review the file, commit it.
- Change a prompt: edit `packages/prompts/<task>/*.md` (file default) or create a version in the admin UI. Templates are domain-neutral; context arrives through `{rag_context}`.
- Add a page: `apps/web/app/(workbench)/...` or `(admin)/...`; add its prefix to `ROLE_PREFIXES` in `middleware.ts` and to `NAV` in `components/layout/shell.tsx`.

## 4. Conventions
- Branches: `feat/<area>-<short>`, `fix/…`, `docs/…`. PR into `main`, one approval, CI green (`test`, `lint`, `scrub`).
- Commits: conventional (`feat(rag): …`). Keep migrations in their own commit.
- Python: ruff (line 140), typed SQLAlchemy 2.0 models, Pydantic v2 schemas.
- TypeScript: strict, no `any`, shadcn primitives in `components/ui`, tokens in `globals.css` only.
- Never commit anything under `data/`, `.env`, or model weights.

## 5. Team split (proposed)
| Workstream | Owner | First task |
|---|---|---|
| A Ingestion & grounding | lead | retrieval eval set (30 Qs) + hybrid search |
| B Planning & pedagogy | | `generate_plan` handler + plan editor |
| C Asset generation & export | | `generate_lesson_assets` + citation validator |
| D Video & optimisation | | TTS voices vendored + `render_video`; vLLM bring-up on the H100 |

See `docs/ROADMAP.md` for milestones and dates.
