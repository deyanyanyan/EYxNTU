# Evaluation framework: implementation plan

**Status:** proposal for team review · drafted 8 October 2026 · supersedes the "Lesson authoring and gates", "Evaluation evidence" and "Video and LMS export" rows of the [roadmap](ROADMAP.md) once agreed.

## 1. Why this plan exists

EY's feedback after the baseline demo:

> - Prefer to have an **agentic evaluation layer**.
> - Evaluation in two steps: **align the evaluation system to subject-matter experts** (human in the loop); once that is verified, **use it as a benchmark layer**.
> - LMS built on a **frontier model, scaled down to a local model** (Qwen 30B). **Does performance drop?** Frontier models are needed as the benchmark.

What that means for us:

| EY asked | What we build |
|---|---|
| Agentic evaluation layer | A scorer that rates every generated plan and lesson on grounding, coherence and pedagogy, and returns pass / revise / escalate with a reason |
| Step A: align to SMEs | Before trusting any AI judge, show that it agrees with human raters on a blind, labelled sample (the **gold set**) |
| Step B: use it as a benchmark | Freeze the judge that passed, then use it to score every model on the same inputs (the **leaderboard**) and as the gate inside the pipeline |
| Frontier → local, does it drop? | Run the same pipeline with Gemini, Claude and Qwen 30B (plus today's Qwen 7B) and report the gap per dimension, with cost and latency |

**New features are paused.** Narrated video/TTS is shelved. PPTX and SCORM export stay as they are; EY already has export.

### Who the SMEs are

An SME (subject-matter expert) is someone who knows the course material well enough to judge whether a lesson is correct and teaches well. In order of preference:

1. **EY reviewers** (L&D, instructional design, or the owners of the source documents). Ask EY whether they can give a few hours each.
2. **Fallback: our four team members** as blind raters using the written rubric, on a corpus we can judge ourselves (the fictional Northwind handbook plus public training material). The report must then say "team raters, not domain experts".

Either way the labelling load is small: roughly 3–4 hours per rater, once, plus spot checks later.

## 2. Team structure

The framework is the product. Each model is an **arm** that plugs into it.

```
                    ┌─────────────── evaluation framework (lead) ───────────────┐
 Arm G  Gemini   ──┐│ frozen corpus + course brief + prompts                    │
 Arm Q  Qwen 30B ──┼► generate course (same pipeline, only the model changes)   ├──► leaderboard
 Arm F  Claude   ──┤│ score: 1 deterministic checks                             │    per arm × dimension
 Arm B  Qwen 7B  ──┘│        2 AI judge (never judges its own arm)              │    + time, calls, cost
   (baseline)       │        3 blind human labels (gold set, checks the judge)  │
                    └───────────────────────────────────────────────────────────┘
```

| Role | Owner | Owns |
|---|---|---|
| Framework lead | Project owner | Arm interface, runner, scorers, labelling sheet, agreement analysis, leaderboard, final report. Also runs Arm B (the existing Qwen 7B baseline) |
| Arm G | Teammate 1 | Gemini API: access, key handling, structured-output reliability, rate limits, cost tracking |
| Arm Q | Teammate 2 | Qwen 30B: hardware, serving (vLLM or Ollama), context window, memory and latency measurements |
| Arm F | Teammate 3 | Frontier model (Claude by default; see open decisions): access, key handling, structured output, cost tracking |
| Everyone | All four | Blind labelling of **other arms'** outputs, PR review, demo |

Arm owners do not change prompts, retrieval or the pipeline on the main track (see section 5). Their job is to make their model run reliably through the shared pipeline and to report where it breaks.

## 3. How the existing code is used

Most of the pipeline exists already (see [handoff](HANDOFF.md) section 2e):

- Every model call goes through `apps/api/app/core/llm/client.py`, an OpenAI-compatible client configured by `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`. Gemini and Claude both expose OpenAI-compatible endpoints and Qwen 30B can be served by vLLM or Ollama, so **an arm is mostly configuration**. Each arm owner confirms this for their model in week 1; anything that does not work through the compatible endpoint becomes a small adapter in `client.py`.
- `scripts/course_baseline.py` already runs upload → plan → approve → lessons → export and writes a JSON record. The runner extends it.
- `app/core/generation/critique/` already scores grounding, coherence and pedagogy with prompts in `packages/prompts/critique/`. This becomes the AI judge.
- The schema already has `Asset.grounding_score`, `coherence_score`, `pedagogy_score`, `critique` and `Review` for the pipeline gate.

### Code changes the framework needs

| Change | Why |
|---|---|
| Separate judge settings (`JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_MODEL`) in `config.py` and `client.py` | Today generator and critic share one model; the judge must be chosen independently of the arm being scored |
| Per-arm context window and max tokens | The 16k guard is right for local Ollama; frontier arms have larger windows. Keep the evidence budget (`MAX_EVIDENCE_TOKENS`) **fixed across arms** so they see the same evidence |
| Record token usage and cost from each response | `llm_call_count()` counts calls only; the leaderboard needs tokens, cost and latency per arm |
| Run manifest | Git SHA, arm config, prompt version IDs, corpus hash and judge config saved with every run, so results can be reproduced |
| Fix citation loss on re-ingestion (`Citation.chunk_id` cascade, ticket S1-04) **before** labelling | Re-uploading a source would silently delete citations from labelled lessons and corrupt the gold set |

## 4. Framework components

Everything new lives in `packages/eval/` (Python, run inside the `api` container like the existing scripts).

```
packages/eval/
  arms/
    baseline-qwen7b.yaml       # committed: model name, base URL, context, params
    gemini.yaml
    qwen30b.yaml
    frontier.yaml
    .env.<arm>                 # gitignored: API keys only
  corpus/
    manifest.yaml              # documents, origin, licence, hash; public or fictional only
    briefs.yaml                # frozen course briefs (audience, duration, goals)
  rubric.md                    # human and AI rubric, with anchored examples per score
  run.py                       # generate one course per arm × brief → runs/<run_id>/
  score.py                     # deterministic checks + AI judge → scores.jsonl
  label_export.py              # blind labelling sheet (CSV) with arm names hidden
  agreement.py                 # human-human and judge-human agreement on the gold set
  leaderboard.py               # results table (Markdown + CSV) across arms
  README.md
```

### 4.1 Arm interface

An arm is a YAML file plus a gitignored key file:

```yaml
# packages/eval/arms/gemini.yaml
id: gemini
owner: teammate-1
base_url: https://<provider OpenAI-compatible endpoint>
model: <exact model id>
api_key_env: GEMINI_API_KEY
context_tokens: 128000
max_tokens: 4096
temperature: 0.3
price_per_mtok: { input: <n>, output: <n> }   # for the cost column; 0 for local
notes: ""
```

`run.py --arm gemini --brief northwind-30min` restarts `api` and `worker` with the arm's settings, runs the full pipeline, and writes:

```
runs/<run_id>/
  manifest.json      # git SHA, arm, prompts, corpus hash, timings
  course.json        # plan, lessons, slides, quizzes, citations
  metrics.json       # calls, tokens, cost, wall clock per step, failures
```

Runs are **not** committed (they go under `data/artifacts/eval/`); only small summary tables and the gold-set labels are.

### 4.2 Scoring layers

| Layer | What it checks | Trust |
|---|---|---|
| 1 Deterministic | Citation points at a real chunk; quoted span appears in the source (quote and whitespace normalised); uncited bullets; lesson-to-lesson overlap (shared chunks and embedding similarity); quiz validity | Cannot flatter itself. Required under every AI judgement |
| 2 AI judge | Grounding per bullet (supported / unsupported / not a claim); coherence and pedagogy per lesson (1–5 with anchored rubric); one-line reason each | Trusted only after it passes the gold-set check (section 6) |
| 3 Human | The same rubric, blind, on the gold set; spot checks afterwards | Reference for layers 1 and 2 |

**Judge rule:** no model judges its own arm's output. Each lesson is scored by every judge that is not its generator, so self-preference can be measured rather than assumed.

### 4.3 Leaderboard

One table per brief, one row per arm (and later per arm × single-pass / gated):

| Arm | Grounding (% bullets supported) | Coherence (1–5) | Pedagogy (1–5) | Lesson overlap | Valid citations | Wall clock | Calls | Tokens | Cost |
|---|---|---|---|---|---|---|---|---|---|

Each score shows its spread across repeated runs (at least 3 runs per arm). The headline answer to EY is the frontier-vs-Qwen 30B gap per column.

## 5. Experimental rules

- **Main track: change only the model.** Same corpus, briefs, prompts, retrieval settings and evidence budget for every arm. Otherwise we would be comparing who prompted best, not which model is best.
- **Optional tuned track** (only if time allows): arm owners may adapt prompts for their model; reported separately and never mixed into the main table.
- **Tune judge prompts on the dev half of the gold set only**; report agreement on the held-out half.
- **Thresholds come from data.** Pass / revise / escalate cut-offs are set from the gold set, not chosen in advance.
- **Data policy (ADR-003, to be written):** frontier APIs are used **only at development and evaluation time, only on public or fictional documents**. The shipped product stays air-gapped and runs the local model. API keys live in gitignored env files and are never committed or printed.

## 6. Phases

### Phase 0 — Reset (8–16 Oct)

- Agree this plan; answer the open decisions (section 8).
- Write ADR-003 (frontier models as offline reference only).
- Freeze corpus and briefs: Northwind handbook plus 1–2 public documents (reuse the sprint 1 corpus manifest if it exists).
- Each arm owner gets their model answering one plan call through the shared client and reports what broke.
- Arm Q secures hardware. Qwen 30B at 4-bit needs roughly 18 GB+ of memory for weights alone; it will not fit comfortably in a 16 GB laptop's Docker allocation. Confirm the exact checkpoint (likely Qwen3-30B-A3B) and a GPU or high-memory machine in week 1.
- Fix the citation re-ingestion bug (S1-04).

**Exit:** four arms each complete one plan call; corpus and briefs committed; ADR-003 merged.

### Phase 1 — Framework v1 and first runs (19–30 Oct)

- Lead: arm config loading, judge settings, usage/cost recording, run manifest, `run.py`, deterministic scorer, first leaderboard (deterministic columns only).
- Arm owners: full course run on their arm, 3 repeats; fix reliability issues in their adapter only.
- Lead + team: write `rubric.md` with anchored examples; pilot it on 2 lessons together to align on meanings.

**Exit:** every arm has 3 complete runs; leaderboard shows deterministic metrics, time, calls and cost.

### Phase 2 — Gold set and judge calibration (EY step A) (2–13 Nov)

- `label_export.py` samples lessons across arms (proposal: 6 lessons per arm = 24 lessons), hides the arm, and assigns each lesson to **2 raters who did not generate it**.
- Raters label grounding per bullet and coherence/pedagogy per lesson (about 12 lessons each, 3–4 hours).
- `agreement.py` reports:
  - **human-human agreement** (Cohen's kappa on bullets, weighted kappa on 1–5 scores) — the ceiling;
  - **judge-human agreement** for each candidate judge (Gemini, Claude, Qwen 30B, Qwen 7B), excluding self-judging;
  - **judge recall on human-flagged failures** — a judge that approves everything can look accurate on averages.
- Split 50/50 into dev and held-out. Tune judge prompts on dev; report on held-out.
- **Pass bar (provisional, confirm after the human-human result):** judge agreement within 0.1 kappa of human-human agreement, and at least 80% recall on failures. Freeze the passing judge(s): model, prompt version, thresholds.

**Exit:** a frozen, verified judge with its agreement numbers. If no local judge passes, that is a finding: report it, and use the best frontier judge for benchmarking only.

### Phase 3 — Benchmark: does performance drop? (EY step B) (16–27 Nov)

- Score every run with the frozen judge; publish the full leaderboard.
- Add the gated condition: generation → judge → bounded revision (max 2) → escalate. Run it for Qwen 30B (the shipping candidate) and, if budget allows, Qwen 7B.

| | Single pass | Gated |
|---|---|---|
| Gemini, Claude | Ceiling | — (optional) |
| Qwen 30B | **Target** | **Target + gates** |
| Qwen 7B | Current baseline | Baseline + gates |

- Human spot check: 10% of judge verdicts re-labelled blind to catch drift.

**Exit:** answers, with numbers: how much quality drops from frontier to Qwen 30B per dimension; whether gating closes the gap; what gating costs in time and calls.

### Phase 4 — Gate in the product (30 Nov–11 Dec)

- The frozen **local** judge runs after each plan and lesson in the pipeline and writes scores and reasons to `Asset` / `Review`.
- Pass continues; revise triggers bounded revision; escalate goes to the instructor with the failed check shown.
- Every escalation decision is appended to the gold set (continuous human in the loop).
- UI: verdict badge and reason on each lesson in the Course tab.

**Exit:** a gated course runs end to end on the local model, with verdicts visible in the UI.

### Phase 5 — Report and handover (7–18 Dec)

Evaluation report (the product claim and the report are the same deliverable), demo, sample course, reproducible commands, offline rehearsal evidence.

## 7. Risks

| Risk | Mitigation |
|---|---|
| No EY SMEs available | Team raters with blind labelling; report the limitation |
| Humans disagree with each other | That sets the ceiling; report it. Tighten the rubric with anchored examples before labelling |
| Qwen 30B hardware not available | Escalate in week 1; fall back to a quantised build on the largest available machine and record the configuration |
| Judges favour their own model | No self-judging; measure cross-judge differences explicitly |
| Frontier API cost or rate limits | Price per arm in config; cap runs; record cost in the leaderboard |
| Arm owners drift into prompt tuning | Main track forbids it; tuned track reported separately |
| Gated runs too slow on CPU | Run gated experiments on Arm Q's hardware; report wall clock |
| Sensitive data sent to external APIs | Public or fictional corpus only (ADR-003) |

## 8. Open decisions

Defaults are used until the team decides otherwise.

| Decision | Default |
|---|---|
| Who are the human raters? | Ask EY for reviewers; team raters as fallback |
| Frontier arm: Claude or an OpenAI model? | Claude; one model only |
| Exact Qwen 30B checkpoint and hardware | Qwen3-30B-A3B, to confirm in Phase 0 |
| Does "scale down" mean model swap or distillation? | Model swap. Distillation means fine-tuning, which the brief rules out; confirm with EY |
| Is EY satisfied with a public / fictional corpus? | Yes, required for frontier arms |
| Frontier API budget | To set in Phase 0 |
| Tuned track in scope? | Only if Phase 3 finishes early |
