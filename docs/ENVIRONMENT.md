# Environment configuration

Each teammate owns one private root `.env`, generated from `.env.example` by the setup scripts. The Compose wrappers explicitly load it. Never commit or share it.

## Local defaults

| Setting | Purpose |
|---|---|
| `COMPOSE_PROFILES=cpu` | Starts Ollama alongside PostgreSQL, API, worker and web |
| `POSTGRES_USER/PASSWORD/DB` | Local database credentials; setup generates a random password |
| `DATABASE_URL` | API/worker DSN; the Docker hostname is `postgres` |
| `SECRET_KEY` | Random JWT signing secret generated during setup |
| `DEFAULT_ADMIN_EMAIL/PASSWORD/NAME` | Creates the first admin only when the users table is empty |
| `LLM_BASE_URL=http://ollama:11434/v1` | Local inference endpoint inside the Compose network |
| `LLM_MODEL=qwen2.5:7b-instruct` | Model name; pull the exact configured name in Ollama |
| `LLM_API_KEY` | Placeholder required by the client; no external service key is needed |
| `LLM_TIMEOUT_SECONDS=300` | Model request timeout; CPU generation may need adjustment |
| `OLLAMA_CONTEXT_LENGTH=16384` | Context window the Ollama server serves. Its own default is 4096 and it truncates longer prompts silently |
| `LLM_CONTEXT_TOKENS=16384` | Same number on the client side; the API refuses an oversized prompt rather than letting the server drop evidence |
| `EMBEDDING_MODEL=BAAI/bge-m3` | Local sentence-transformers model |
| `EMBEDDING_DIM=1024` | Must match the database vector width |
| `EMBEDDING_DEVICE=cpu` | API/worker Docker images contain CPU PyTorch, including the GPU serving profile |
| `EMBEDDING_BATCH_SIZE=32` | Lower this if document embedding exceeds available memory |
| `HF_HOME=/data/models/hf` | Shared, persistent Hugging Face model cache |
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | Start at 0; set to 1 after preparation and test offline behavior |
| `RAG_TOP_K=6`, `RAG_SIMILARITY_THRESHOLD=0.45` | Initial retrieval settings; calibrate against the labelled corpus |
| `CHUNK_SIZE=1500`, `CHUNK_OVERLAP=300` | Character-based chunking settings |
| `DATA_DIR=/data` | Container mount of the repository's local `data/` directory |
| `MAX_UPLOAD_MB=200` | Maximum uploaded file size |
| `API_PORT=8000`, `WEB_PORT=3000`, `POSTGRES_PORT=5432` | Host ports; published on loopback only |
| `NEXT_PUBLIC_API_URL=http://localhost:8000` | Browser-facing API address; rebuilding web is required after changing it |
| `CORS_ORIGINS=http://localhost:3000` | Allowed browser origins; comma-separated |
| `WORKER_POLL_SECONDS=2`, `WORKER_MAX_JOB_MINUTES=120` | Queue polling and stale-job timeout |
| `PROMPTS_DIR` | Compose supplies `/srv/packages/prompts` |

Database and account credentials persist in the database. Regenerating `.env` does not rotate existing database or user passwords. Keep the original file when pulling updates.

Changing the embedding model requires a deliberate index migration/re-embedding strategy. The present model check alone does not safely migrate a mixed index.

## Optional services

TTS is excluded from normal startup. Enable it with `--profile media`; the current image installs Piper. Voices must be supplied separately. Kokoro, video rendering and packaging need further implementation and verification.

The `gpu` profile is experimental and intended for a Linux NVIDIA host with container GPU support. It changes LLM serving to vLLM, serving one base model plus the team's custom LoRA adapters; it does not add GPU access to the API/worker. Prepare the model bundle and set `LLM_BASE_URL=http://inference:8000/v1`. Set `LLM_MODEL` to the base model's served name or to an adapter name. See [inference notes](../services/inference/README.md) for the bundle, release steps and sizing.

## GPU profile and custom models

| Setting | Purpose |
|---|---|
| `VLLM_MODEL` | Base model: a hub id already in `HF_HOME` (the server runs offline) or a directory under `/data/models` |
| `VLLM_REVISION` | Pinned hub revision of the base; `make models-verify` requires it to match `infra/models.lock.json` |
| `VLLM_BASE_ID` | Hub id of the base when `VLLM_MODEL` is a directory, so adapters can be checked against it |
| `VLLM_MAX_MODEL_LEN`, `VLLM_GPU_MEMORY_UTILIZATION` | Server context window and GPU memory share |
| `VLLM_LORA_MODULES` | Space-separated `name=dir` adapters under `data/models/adapters`; each name becomes a model the app can request. The server refuses to start if an adapter was trained on a different base or revision |
| `VLLM_MAX_LORAS`, `VLLM_MAX_LORA_RANK` | Adapter slots held at once, and the largest LoRA rank (the reviewer uses 16) |
| `VLLM_EXTRA_ARGS` | Further `vllm serve` flags, appended verbatim |
| `REVIEWER_ENABLED=false` | Keep off until a validated reviewer adapter passes `make served-check` |
| `REVIEWER_BASE_URL`, `REVIEWER_API_KEY`, `REVIEWER_MODEL` | The reviewer endpoint and its served adapter name; it is separate from `LLM_*`, so the generator is unaffected |
| `REVIEWER_MAX_TOKENS`, `REVIEWER_TIMEOUT_SECONDS` | Reply budget and request timeout for one review |
| `REVIEWER_CONTEXT_TOKENS=8192` | Reviews must fit without truncation, as in training; longer ones are split into scoped cases |
| `REVIEWER_ENABLE_THINKING=false` | The adapter was trained and evaluated with the template's thinking mode off |

## Development outside Docker

Optional: Python 3.12 and Node 20. Install Python requirements with `-c constraints.txt` after obtaining the matching CPU torch wheels; run `npm ci` for the web app. The supported teammate path is Docker.

Override `DATABASE_URL` to use `localhost` and set a writable host `DATA_DIR`. Model cache paths in the Docker `.env` refer to container paths and must also be overridden. Never change the shared template to a developer-specific absolute path.