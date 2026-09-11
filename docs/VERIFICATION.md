# Local verification record

Verified on 11 September 2026 in the working checkout. These results describe this machine and the small operational fixtures; they are not a four-machine sign-off or a content-quality benchmark.

## Tested environment

- Windows host running Docker Desktop's Linux x86_64 engine.
- Docker Engine 29.2.1 and Compose 5.0.2.
- Docker reported 20 CPUs and approximately 15.5 GiB available memory.
- Python 3.12 containers with CPU PyTorch; resolved package versions in `apps/api/constraints.txt`.
- Next.js 15.5.25 from the committed npm lockfile.
- Ollama 0.34.0 with `qwen2.5:7b-instruct` (model ID `845dbda0ea48`, approximately 4.7 GB).
- BGE-M3 embeddings and Docling 2.126.0.

PostgreSQL and Ollama image digests are recorded directly in Compose. Python/Node base image tags are not immutable; retest when upgrading dependencies or images.

## Checks performed

| Check | Result |
|---|---|
| Environment generation into a separate temporary file | Passed; random configuration generated, existing credentials preserved |
| Re-running Windows setup with an existing environment | Passed; existing configuration retained |
| Base and development Compose configuration validation | Passed |
| Production API, worker and web image builds | Passed |
| Default CPU stack startup and readiness | Passed for PostgreSQL, API, worker, web and Ollama |
| Backend tests | 11 passed |
| Python error checks | `ruff check . --select F` passed |
| Python dependency consistency | `pip check` passed |
| Frontend lint, TypeScript and production build | Passed |
| Application smoke | Web login page, database health, authentication, current user, project create/read/update/delete and jobs passed |
| Real document ingestion and source-scoped search | TXT, DOCX, PPTX and PDF passed using generated fixtures and real embeddings |
| Primary document parser | Worker logs confirmed Docling conversion for the DOCX, PPTX and PDF fixtures |
| Local model client | Qwen returned schema-valid structured JSON |
| Restart persistence | A saved disposable project and user login survived restarting PostgreSQL, API and worker |
| Ingestion after restart | All four fixture formats passed again |
| Repository checks | PowerShell and Bash identifier scans passed; `git diff --check` passed |

The ingestion fixture checks for the known phrase “30 days” in source-scoped retrieval with a zero similarity threshold. This establishes operational retrieval and provenance fields, not retrieval quality or a calibrated threshold. The sprint's labelled 30-question corpus provides that evaluation.

The restart check removes its saved project after verification. Ingestion smoke fixtures are also removed. Downloaded model caches remain locally under ignored `data/models/`.

## Known limits and next verification

- Other teammates' Windows, Linux and Apple Silicon environments have not yet been tested.
- The development override was configuration-validated; the exercised application ran production images.
- Networking was available for initial image/model preparation. A disconnected, fully air-gapped rehearsal remains a sprint task.
- GPU serving, optional TTS voices, rendering and SCORM are not validated by these checks.
- Agent tool calling, saved approval/resume workflows and generation quality remain upcoming work.
- Job/project permissions, exact citation validation and safe source re-ingestion remain explicit sprint backlog items.
- GitHub CI configuration has been added but has not yet run on GitHub.
- Changes are left uncommitted in the working tree. The project owner will handle committing and pushing.

## Repeat the checks

Follow [onboarding](ONBOARDING.md) for startup, model preparation and the saved-project restart sequence. The default `smoke.py` requires no model download; add `--ingest --llm` for the full operational check.

The health dependency change follows [Docker's startup-order guidance](https://docs.docker.com/compose/how-tos/startup-order/). The standalone frontend binds to all container interfaces as described in [Next.js standalone output documentation](https://nextjs.org/docs/15/app/api-reference/config/next-config-js/output); Compose publishes host ports on loopback.