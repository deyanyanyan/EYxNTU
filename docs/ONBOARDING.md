# Teammate onboarding

## Prerequisites

Use Git and a running Docker engine with Linux containers and Compose v2.24 or newer. Windows teammates should use Docker Desktop's WSL2 backend. Native Windows containers are unsupported.

For planning, allow around 16 GB system RAM and 30 GB free disk for images, caches and a 7B model; this is a working budget, not a measured minimum. CPU generation can be slow. Start with the application foundation before downloading models.

Follow the platform-specific commands in [README](../README.md). Both wrappers resolve paths relative to the repository, so a checkout path with spaces is supported. The first build downloads dependencies. Later starts reuse images and caches.

Setup creates `.env` only when it is missing. Read the generated admin credentials locally. Do not regenerate credentials against an existing database: PostgreSQL and existing users retain their original passwords.

## Prepare models and check document search

In the commands below, `sh scripts/compose.sh` is the macOS/Linux wrapper. On Windows replace it with `powershell -ExecutionPolicy Bypass -File scripts/compose.ps1`. Everything executes inside Docker.

Pull the model named in your `.env` (the default is shown):

```sh
sh scripts/compose.sh exec ollama ollama pull qwen2.5:7b-instruct
sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py --ingest --llm
```

The ingestion check creates a disposable project, uploads generated TXT, DOCX, PPTX and PDF fixtures, waits for the worker, checks source-scoped search and removes its own sources/project. It uses real embeddings. The first run may download BGE-M3 and document-parser models into mounted caches. Logs show which parser was used; a basic-parser fallback is not proof of Docling success.

The LLM check requests schema-validated JSON from the local server. It is a basic compatibility check; agent tool calling and quality comparisons remain sprint deliverables. If you choose a smaller model, set `LLM_MODEL` in `.env`, pull that exact model and recreate the API/worker.

After the bootstrap password has been changed, the smoke script's default login will fail unless its credentials are supplied to the container through matching environment values. Do not reset the database to solve a login typo.

## Daily commands

```sh
sh scripts/compose.sh up --build --wait
sh scripts/compose.sh ps
sh scripts/compose.sh logs --tail=100 api worker
sh scripts/compose.sh exec -T api python -m pytest -q
sh scripts/compose.sh exec -T api ruff check . --select F
sh scripts/compose.sh stop
sh scripts/compose.sh down
```

`stop` and `down` preserve the database volume and local `data/` files. Avoid `down -v`: it deletes the local database. Never delete volumes as part of routine updates.

To update from GitHub, pull the branch and run `up --build --wait`. The API applies committed Alembic migrations before becoming healthy. The worker starts only after API readiness.

Frontend lint and TypeScript checks run during the production image build. For local development with hot reload:

```sh
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.dev.yml up --build
```

The web development container uses `npm ci`. Restart the worker after Python worker/core edits; its process does not automatically reload. After using development mode, run the normal startup command to return to production images.

To check database persistence explicitly:

```sh
sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py --save-restart
sh scripts/compose.sh restart postgres api worker
sh scripts/compose.sh up --wait
sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py --verify-restart
```

This preserves one disposable project across restart, verifies its values, then removes it. Run `--verify-restart` to finish an interrupted check before starting another.

Python dependencies are constrained in `apps/api/constraints.txt`; frontend dependencies use `package-lock.json`. PostgreSQL and Ollama use tested image digests. Update these deliberately and repeat the smoke checks. The GPU image and base OS image tags remain separate upgrade considerations.

## Offline rehearsal

Offline operation is a target to verify, not a consequence of a green health check.

1. While online, build every required image, pull the chosen LLM, and run all four ingestion checks.
2. Retain the entire `data/models` cache and all required Docker images.
3. Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` in `.env`.
4. Recreate API and worker, disconnect external networking, then rerun `smoke.py --ingest --llm`.
5. Record parser selection, any attempted downloads, failures and timings. Do not claim PDF layout parsing passed if the basic fallback was used.

A clean machine without these images and weights needs an online preparation phase or a separately prepared offline bundle. Speech voices, rendering tools and GPU deployment are outside the default laptop setup.

## Troubleshooting

| Symptom | Action |
|---|---|
| Docker daemon / pipe unavailable | Start Docker Desktop; wait for the Linux engine to be ready |
| Port already allocated | Stop the conflicting local service or change ports in `.env`; update the browser API URL and CORS origin together |
| Database authentication fails after editing `.env` | Restore the original database credentials; existing volumes are not reinitialized |
| Login fails | Use credentials from your own `.env`; old checkouts may still use `admin@lms.local` |
| UI loads but API is unreachable | Check `NEXT_PUBLIC_API_URL`, then rebuild web; it is embedded at build time |
| API unhealthy | Inspect API logs for migration/configuration failures and database health |
| Source stays queued | Inspect worker logs; app readiness alone does not exercise job execution |
| Model missing / connection refused | Check the selected CPU/GPU profile, pull the model and inspect inference logs |
| First ingestion is slow | Watch worker logs; model download and first inference can take several minutes |
| Out of memory | Give Docker more memory, reduce embedding batch size, or use a smaller LLM |

## Before sharing on GitHub

Commit source, migrations, `package-lock.json`, docs, scripts and CI configuration. Keep runtime data and credentials out of Git. Review `git status --short`, run the scrub check, then inspect the staged diff before committing. The supplied Word proposal and HTML brief are project references; confirm they belong in the team's repository before adding them.

This checkout initially had no Git remote. Configure the intended GitHub repository before the first push. No teammate needs your `.env` or your database volume.
