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
| `JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_MODEL` | Optional, separate model target for the offline batch benchmark. No judge is configured by default and the generator is never used as a silent fallback |
| `JUDGE_TEMPERATURE`, `JUDGE_MAX_TOKENS`, `JUDGE_TIMEOUT_SECONDS`, `JUDGE_CONTEXT_TOKENS` | Optional judge request settings; apply only to the benchmark scorer |
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

The `gpu` profile is experimental and intended for a Linux NVIDIA host with container GPU support. It changes LLM serving to vLLM; it does not add GPU access to the API/worker. Prepare and configure `VLLM_MODEL` before starting it. Use the same served name for `LLM_MODEL`; adjust `LLM_BASE_URL=http://inference:8000/v1`. See [inference notes](../services/inference/README.md).

## Development outside Docker

Optional: Python 3.12 and Node 20. Install Python requirements with `-c constraints.txt` after obtaining the matching CPU torch wheels; run `npm ci` for the web app. The supported teammate path is Docker.

Override `DATABASE_URL` to use `localhost` and set a writable host `DATA_DIR`. Model cache paths in the Docker `.env` refer to container paths and must also be overridden. Never change the shared template to a developer-specific absolute path.
