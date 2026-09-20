# Session handoff

Working notes for whoever (or whatever) picks this up next. Not a team document —
`README.md`, `docs/ROADMAP.md` and `docs/project-brief.html` are the ones the team reads.

**Written:** 21 September 2026 · **Base commit:** `64c3a40` on `main` · **All changes below are uncommitted.**

The project owner is acting as PM, not implementer. They are comfortable with product
reasoning and delegation, less so with the code. Explain consequences, not mechanisms,
and keep implementation detail out of the way unless asked for it.

---

## 1. The most important thing to know

**EY gave feedback that changes the project's positioning.** They already have a prototype
that turns documents into a course end to end, so generating a course is not this team's
contribution. The contribution is now the **agentic evaluation layer**: every generated step
is scored against the source evidence that produced it, returns pass / revise / escalate,
and records why.

Consequences already applied to the docs:

- Export (video, SCORM) shrinks — it is the least differentiated work and EY has it.
- Evaluation moves *before* export in the schedule, not after it.
- The evaluation report and the product claim are now the same deliverable.
- The repo's schema already anticipated this: `Asset.grounding_score` / `coherence_score` /
  `pedagogy_score` / `critique`, plus `Review`, `ApprovalState`, and prompt files in
  `packages/prompts/critique/`. Lean on what exists.

**The standing risk to keep raising:** a 7B model scoring its own output will approve it.
Three safeguards are written into the brief as deliverables — a deterministic code check under
every gate, an instructor agreement study, and the single-pass / fixed-revision / gated ablation.
Do not let score thresholds be invented; they come from a measured baseline.

---

## 2. What was done this session

### 2a. Verified the local model (no code change)

The team believed local Qwen serving was the blocking problem. It is not — it was already
working, and `docs/VERIFICATION.md` (11 Sep) reproduced exactly. Beyond that, the open
questions in ADR-001 were closed by direct probing:

| Check | Result | Time |
|---|---|---|
| Plain chat | pass | 1.1 s |
| Nested structured output (quiz schema) | pass | 28.6 s |
| Verbatim `source_span` grounding | 2/2 spans found | — |
| **Tool calling** | pass — correct function, well-formed args | 6.7 s |
| **Tool result round-trip** (multi-turn) | pass | 6.0 s |

**Tool calling works on `qwen2.5:7b-instruct` via Ollama.** Agent orchestration on the CPU
profile is viable; no GPU needed to start. Do not re-measure this — it is recorded in ADR-001.

### 2b. Fixed a silent context-truncation defect

Ollama served a 4096-token window (its default, not the 32k the architecture assumed) and
**dropped the oldest tokens with no error**. A needle at the start of a 13.5k-token prompt
vanished and the model answered confidently from what remained. Every grounding measurement
built on that would have been invalid.

Per-request `extra_body={"options": {"num_ctx": ...}}` is **ignored** by Ollama's
OpenAI-compatible endpoint. The window is server configuration.

Changes:

| File | Change |
|---|---|
| `infra/docker-compose.yml` | `OLLAMA_CONTEXT_LENGTH: ${OLLAMA_CONTEXT_LENGTH:-16384}` on the `ollama` service |
| `apps/api/app/config.py` | `llm_context_tokens: int = 16384` |
| `apps/api/app/core/llm/client.py` | `ContextOverflowError`, `estimate_tokens`, `prompt_token_budget`, `_guard_context`, `_warn_if_truncated`; guards wired into `chat_text` and `chat_structured` |
| `apps/api/tests/test_context_guard.py` | new, 9 tests |
| `.env.example`, `.env` | `OLLAMA_CONTEXT_LENGTH=16384`, `LLM_CONTEXT_TOKENS=16384` |
| `docs/ENVIRONMENT.md`, `docs/adr/001-model-serving.md`, `services/inference/README.md` | documented, incl. memory and latency costs |

Verified end-to-end after the fix:

```
evidence at ~13.5k tokens    RECALLED   'BLUEHERON-77'     (was: silently lost)
evidence at ~30k tokens      REFUSED    "Prompt is ~34738 tokens but only 16128 fit..."
```

The guard is re-checked inside `chat_structured`'s retry loop, because each repair round
appends the bad output plus the validation error and can outgrow the window mid-loop.

`prompt_token_budget()` exists so retrieval code can pack chunks to fit rather than crash —
use it when the planning and lesson agents are built.

**Backward compatible.** A teammate with an older `.env` still gets 16384 from the Compose
default and the pydantic default. `scripts/gen_env.py` copies from `.env.example`, so new
clones pick the vars up automatically.

### 2c. Rewrote the project brief around the new positioning

`docs/project-brief.html` — same four-page A4 print format and visual identity, new content.
Page 1 states where the contribution sits relative to EY's prototype, the three gate checks
(grounding / coherence / pedagogy) and the three honesty safeguards. Page 2 has the resequenced
timeline and revised A–D ownership. Both SVG diagrams were rebuilt: architecture now shows the
evaluation layer between generation and storage; the workflow diagram shows the pass / revise /
escalate gate on each step with its bounded revision loop.

`docs/ROADMAP.md` was aligned — it cites the brief as scope authority and would otherwise
contradict it. Added a "Contribution" section and two new risk rows.

### 2d. Published a handover page for the team

<https://claude.ai/artifact/38me5NaXBt5YxAfacqyzLS> — project state, dependency ladder, week-two
assignments with blank name slots, green/red flags, risk register, kickoff checklist.

**This page is now partly stale**: it predates the EY feedback, so its 15-week arc and
priorities still show export ahead of evaluation. The week-2 assignments are still correct.
Republish by passing that URL as `url` — do not create a second artifact.

---

## 3. Deliberately NOT fixed

Both were left for teammates A and C as their sprint tickets. The owner was offered them and
has not said to take them. **Ask before implementing.**

| Bug | Where | Consequence |
|---|---|---|
| Citations destroyed on re-ingestion | `apps/api/app/models/asset.py:64` — `Citation.chunk_id` is `ON DELETE CASCADE` to `chunks` | Re-upload a corrected source and every citation on already-approved assets is deleted silently. Ticket S1-04, workstream A. |
| Job endpoints ignore project membership | `apps/api/app/routers/jobs.py` — `get_job:28` checks only that a user is logged in; `stream_job:49` validates the JWT signature and nothing else | Any authenticated user can read or stream any project's jobs. Ticket S1-05, workstream C. |

---

## 4. What's next, in order

1. **Owner decisions first.** Names against workstreams A–D; create the nine sprint tickets
   (`docs/SPRINT_01.md` lists them, they have never been created on GitHub); reset the
   supervisor's expectation that Friday's demo is grounded search, not generated content.
2. **Commit this work.** Nothing here is committed yet. Suggested split: one commit for the
   context fix + tests + env/docs, one for the brief and roadmap rewrite.
3. **Design the gate mechanism** (workstream B). Still the highest-leverage unwritten thing:
   how a job pauses for a human decision and resumes from a checkpoint. The EY pivot makes it
   *more* central, since pass / revise / escalate is the routing decision. No orchestration
   code should be written before this exists as a decision record.
4. **Build the first evaluator** (workstream C). Start with grounding, because the deterministic
   half already exists — `apps/api/app/core/generation/quiz/service.py:47` validates that a
   quoted span appears verbatim in the retrieved context. Generalise that from quizzes to all
   asset kinds, then add the model-scored half on top.
5. **Corpus and 30 labelled questions** (workstream A) — blocks every measurement.
6. **Four-machine setup matrix** (workstream D) — only one Windows machine has ever been verified.
7. **Only then:** planning workflow, lesson authoring, reduced-scope export.

Ask EY for their prototype's output format. If the evaluation layer can score *their* output,
that is a far stronger demonstration than scoring only this team's own.

---

## 5. Running things (Windows host, Docker Desktop)

Docker Desktop may not be running — `"C:\Program Files\Docker\Docker\Docker Desktop.exe"`,
then wait for the engine.

```powershell
cd C:\Users\Mr-De\Downloads\lms-platform
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 up --build --wait
powershell -ExecutionPolicy Bypass -File scripts/compose.ps1 exec -T api python /srv/scripts/smoke.py --llm
```

Or drive Compose directly, which is what actually worked here:

```powershell
docker compose --env-file .env -f infra/docker-compose.yml exec -T api python -m pytest -q
docker compose --env-file .env -f infra/docker-compose.yml exec -T api ruff check . --select F
```

### Gotchas that cost time

- **Git Bash mangles container paths.** `sh scripts/compose.sh exec -T api python /srv/scripts/smoke.py`
  becomes `/srv/api/C:/Program Files/Git/srv/...`. Use the PowerShell wrapper, or set
  `MSYS_NO_PATHCONV=1`.
- **The API container runs the baked image, not your host edits.** After changing Python, run
  `docker compose ... up -d --build api worker` or your new tests simply will not appear.
- **For ad-hoc probes**, `docker cp script.py lms-platform-api-1:/tmp/` then exec it, and delete
  it afterwards. Do not leave files in the container or the repo.
- **Model weights are already cached** in `data/models/ollama` (4.4 GB, `qwen2.5:7b-instruct`,
  ID `845dbda0ea48`). No pull needed. `ollama ps` shows empty after ~5 min idle — that is unload,
  not failure.
- **`.env` is gitignored and contains real credentials.** It was edited locally to add the two
  new vars. Never commit it, never print it.

### Measured on this machine (Windows, Docker 29.2.1, 20 CPU, 15.5 GiB)

- Model resident: 5.1 GB at 4k context, 5.9 GB at 16k.
- 13.5k-token prompt: 177 s, against `LLM_TIMEOUT_SECONDS=300`. Gating multiplies calls 3–4×,
  so a full gated course is hours on CPU. This is the GPU justification.

---

## 6. Verification status

`20 passed` (11 pre-existing + 9 new), `ruff check . --select F` clean, and
`smoke.py --llm` passes both the application and structured-output checks.

Not re-verified since these changes: the `--ingest` fixtures, restart persistence, and the
offline rehearsal. Run `smoke.py --ingest --llm` before claiming the full operational check.
`docs/VERIFICATION.md` has not been updated with this session's results — worth doing when
the work is committed.
