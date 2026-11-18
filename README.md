# LMS Studio

Turns an organisation's documents into a training course, then checks the course against those documents. A writer model plans and writes lessons (slides, speaker notes and quizzes, each bullet cited to its source), a fine-tuned 27B reviewer flags claims the source does not support and scores lesson and quiz quality, and the author exports an editable PowerPoint and a SCORM 1.2 package. Everything runs locally in Docker by default.

Built by an NTU team for EY Tech Consulting, 2026.

**Start with [docs/HANDOVER.md](docs/HANDOVER.md)**: architecture, setup, configuration, evidence and open work.

## Quick start

Install Git and Docker Desktop (Linux containers), start Docker, then from this folder:

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 up --build --wait
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 exec ollama ollama pull qwen2.5:7b-instruct
```

```sh
# macOS / Linux
sh scripts/setup.sh
sh scripts/compose.sh up --build --wait
sh scripts/compose.sh exec ollama ollama pull qwen2.5:7b-instruct
```

Open http://localhost:3000 and sign in with `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` from the generated `.env`.

## Documentation

| Document | Contents |
|---|---|
| [docs/HANDOVER.md](docs/HANDOVER.md) | The full handover: what it does, architecture, running it, configuration, evidence, known issues |
| [docs/USER_FLOW.md](docs/USER_FLOW.md) | Walkthrough of every screen in the web app |
| [docs/MODELS.md](docs/MODELS.md) | The trained reviewer adapters: results, serving, licences |
| [services/inference/README.md](services/inference/README.md) | Model serving: Ollama, vLLM GPU profile, model bundle checks |
| [packages/eval/training/README.md](packages/eval/training/README.md) | How the reviewer was trained and evaluated ([results](packages/eval/training/RESULTS.md)) |
| [packages/eval/benchmark/README.md](packages/eval/benchmark/README.md) | Local against hosted writer benchmark, with scripts to re-run it |
| [packages/prompts/README.md](packages/prompts/README.md) | Prompt templates and versioning |
| `.env.example` | Every configuration variable, documented inline |
