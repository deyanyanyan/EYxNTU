# Batch evaluation benchmark: implementation and scope

**Status:** initial implementation and first captured Gemini-scored batch complete; human calibration and broader benchmark coverage remain · 8 October 2026 · companion to [EVAL_FRAMEWORK_PLAN.md](EVAL_FRAMEWORK_PLAN.md)

## Scope decision

For now, evaluation is a batch benchmark over saved generation runs. It scores and diagnoses model outputs so the team can see what works and what fails for the current generator. It does not make workflow decisions, revise content, or affect the application. The first batch uses the existing Qwen 7B single-pass run and Gemini as an independently configured judge.

This is enough to establish a useful measurement baseline and begin selecting optimization experiments after the EY meeting. It is not enough to claim that the judge is SME-validated or that a quality difference between models is proven. The benchmark must first preserve the exact generation inputs and output, and later be calibrated against human ratings before its scores are treated as authoritative.

Keep the benchmark format independent of any one generator. Future saved runs can represent another Gemini model, Claude or another frontier model, Qwen 30B, a quantized checkpoint, or a tuned model. The initial implementation does not build all those generator arms; it makes their outputs comparable when the team chooses to add them.

## Implementation status

- Added explicit, separately configured judge targeting; no generator fallback is used.
- Added run-bundle capture for lesson outputs, evidence text, source and brief hashes, prompt snapshots, generation settings, and run metadata. The scorer checks captured course/prompt hashes before evaluating.
- Added descriptive citation, evidence-overlap, slide-density, quiz-span, and cross-lesson diagnostics, plus optional grounding/coherence/pedagogy judge scores.
- Added JSONL, CSV, and Markdown batch reports. Reports contain no verdicts or workflow actions; judge prompts and provider usage are preserved when judging is enabled.
- First-run validation: captured and scored the fictional Northwind run `20261008-080910-405b87` in batch `20261008-091733-6e4bc2` with Qwen 2.5 7B and Gemini 3.8 Flash. The report was inspected and the hosted judge request succeeded. SME rubric alignment and broader benchmark coverage remain pending; no automated test suite has been run for this implementation pass.

The implementation is therefore ready for its first controlled run, not yet a validated benchmark result.

## Batch workflow

~~~text
Existing course generation -> immutable run bundle -> batch scoring -> per-run diagnostics and comparison report
~~~

Generation and scoring are separate operations. The evaluator reads a saved bundle containing generated lessons and the evidence that was available to the generator. It then runs deterministic checks and, when configured, the Gemini judge. Re-scoring a bundle with a changed evaluator must not regenerate or alter the content.

The initial unit of evaluation is the finished lesson bundle (slides, quiz, and evidence). The report also summarizes the course and cross-lesson patterns, but does not reduce quality to one pass/fail result. The course plan itself is outside the initial scoring scope. Nothing runs between planning, lesson generation, quiz generation, or export in this first version.

Use the fictional Northwind fixture for the first batch. Any hosted judge or hosted generator must receive only public or fictional material unless EY explicitly approves another data path. The existing 21 September baseline is useful operational context, but it does not contain the lesson-level snapshots and provenance required for this benchmark; the first captured and scored run becomes the evaluation anchor.

## Where the evaluator sits

Now: after the existing single-pass course run has finished, the batch evaluator scores the saved output. It observes the run and writes a report; it does not change the output or control the application.

Later experiment: an in-loop workflow could call a critic after planning or lesson drafting, pass feedback to a generator for revision, and then compare both the first draft and final output. That is a different generation condition, not a change to the batch benchmark. The batch scorer remains the independent measurement step applied after each experimental run. This makes it possible to compare output-only evaluation with critique-in-the-loop, while keeping evaluation itself out of the decision path.

## Starting point before this implementation

Already in the repo:

- The critique helper in *apps/api/app/core/generation/critique/service.py* has grounding, coherence, and pedagogy scoring prompts in *packages/prompts/critique/*.
- *apps/api/app/models/asset.py* has score and critique columns, although batch scoring does not need to write to them.
- Generated slide and quiz assets contain reference tables, and the lesson API returns assets and citations.
- Quiz generation already records accepted and rejected questions and rejection reasons.
- *scripts/course_baseline.py* runs the full course pipeline and records model, calls, timings, and aggregate generation results.

The following gaps motivated the first implementation slice; status is now:

1. Separate judge target: **implemented**.
2. Saved lesson/evidence/prompt run bundle: **implemented; first Northwind capture scored**.
3. Batch scoring command: **implemented; first Gemini-judged batch reviewed**.
4. Deterministic checks and reports: **implemented; needs human review and calibration**.
5. Frozen retrieval benchmark: **still pending**; prepare expected-passage retrieval cases before claiming retrieval improvements.

## Implementation scope

| # | Work | Main files | Done when |
|---|---|---|---|
| 1 | **Independent judge target.** Add JUDGE_BASE_URL, JUDGE_API_KEY, JUDGE_MODEL, JUDGE_TEMPERATURE, JUDGE_MAX_TOKENS, JUDGE_CONTEXT_TOKENS, and JUDGE_TIMEOUT_SECONDS. Let the evaluation code pass an explicit target to the LLM client and cache clients by target. If no judge is configured, run deterministic checks only and record judge status as not requested; never silently use the generator as its own independent judge. Keep credentials out of manifests and output. | *apps/api/app/config.py*, *.env.example*, *docs/ENVIRONMENT.md*, *apps/api/app/core/llm/client.py* | A structured judge request reaches the configured model; existing generation calls still use their current target; missing judge config cannot self-judge. |
| 2 | **Capture immutable run bundles.** Extend *scripts/course_baseline.py* to fetch and save the generated plan, lesson decks, quizzes, citations, and per-asset reference tables before temporary project cleanup. Save a manifest with run ID/time, Git SHA, source and brief hashes, generator model and settings, prompt versions/hashes, retrieval and embedding settings, generation calls/time/errors, and hardware or quantization information when available. Preserve the actual evidence references included with each asset, not only citations the model chose to emit. Store bundles under ignored *data/artifacts/eval/runs/*. | *scripts/course_baseline.py*, *packages/eval/README.md* | A run bundle can be scored later without rerunning generation and identifies the generator configuration and evidence context. |
| 3 | **Evaluation-only deterministic checks.** Add checks for valid citation references, uncited factual bullets, normalized quote/span matches, lexical overlap between a cited bullet and its cited evidence, slide word/bullet density, quiz validator outcomes, and repeated evidence or near-duplicate content across lessons. Treat lexical overlap and lesson overlap as diagnostics, not ground truth or automatic quality failures. Keep quote normalization inside evaluation; do not change quiz accept/reject behavior in this benchmark slice. | New *apps/api/app/core/evaluation/checks.py*; new *apps/api/tests/test_evaluation_checks.py* | Checks run from saved bundle data without a model or database and produce stable counts and findings. |
| 4 | **Batch scorer.** Add a command such as *scripts/evaluate_batch.py* that reads one or more saved run bundles, applies deterministic checks, and scores grounding, coherence, and pedagogy with the explicit judge target. Reuse the three dimension prompts; do not run the existing summary prompt's revise decision or generate pass/revise labels. A judge error is recorded for that lesson and the batch continues. | New *apps/api/app/core/evaluation/service.py*, *scripts/evaluate_batch.py* | The scorer can process a directory of saved runs, reports each lesson separately, and continues when one lesson cannot be scored. |
| 5 | **Per-lesson score records.** Save deterministic counts/findings; each judge dimension's 0–5 score, feedback, and issues; exact judge model and prompt version; judge calls, latency, and provider-reported usage when available; errors; and the run-bundle ID. Missing usage is null, not estimated. No pass/revise/escalate status and no recommended workflow action. | *apps/api/app/core/evaluation/service.py* | Output is versioned, machine-readable JSONL with evidence-linked diagnostics; no fields imply an app decision. |
| 6 | **Batch summary.** Write a compact Markdown/CSV summary grouped by generator run/model, with per-dimension averages and spread, deterministic counts, issue examples, failures, generation time/calls, judge time/calls, and token/cost values only when available. Keep per-lesson rows beside aggregates so a mean cannot hide a failure. | *scripts/evaluate_batch.py*, *packages/eval/README.md* | A single command produces inspectable per-run results and a comparison-ready summary. |
| 7 | **Admin evaluation and report viewer.** Add an Evaluation item to the admin navigation, admin-only routes to list saved run bundles, start/monitor scoring, and read batch reports. The page evaluates already-captured output only; it never starts generation, writes scores to Asset or Review, changes lesson responses, or shows a product verdict. | *apps/api/app/routers/evaluation.py*, *apps/web/app/(admin)/admin/evaluation/page.tsx*, *apps/web/components/layout/shell.tsx* | An admin can choose a saved run, score it with deterministic checks and optional Gemini judging, and inspect the report from the browser; non-admins cannot access run bundles or batch contents. |

### Run bundle and score record

A run bundle is immutable input to scoring. It contains generated content, lesson/quiz citations, the reference passages attached to each generated asset, course brief, source identity/hash, and generation manifest. The reference tables already saved with deck and quiz assets should be captured as the first evidence trace. If a later retrieval experiment needs retrieval ranks/similarity scores that are not present there, add those to the capture format before comparing retrieval variants.

A score record should be diagnostic, not a decision object:

~~~yaml
score_version: 1
run_id: "..."
generator: {arm: "qwen7b-baseline", model: "exact model id"}
lesson_id: "..."
checks:
  citations_invalid: 0
  bullets_checked: 0
  bullets_uncited: 0
  bullets_low_lexical_overlap: 0
  slides_over_density_limit: 0
  quiz_accepted: 0
  quiz_rejected: 0
  course_overlap_findings: []
judge:
  model: "gemini model id, or null"
  prompt_version: "version/hash"
  grounding: {score: 0, feedback: "", issues: []}
  coherence: {score: 0, feedback: "", issues: []}
  pedagogy: {score: 0, feedback: "", issues: []}
  calls: 3
  prompt_tokens: null
  completion_tokens: null
  latency_ms: null
  error: null
~~~

The summary should compare dimensions and findings; do not collapse them into a single pass/fail outcome. Scores are exploratory until the human-alignment stage.

## Definition of done for the initial benchmark

- The existing Qwen 7B baseline can be captured as an immutable bundle with the source, brief, generator configuration, prompts, outputs, and evidence references needed to interpret its scores.
- Evaluation runs as a separate batch command. Running it does not invoke or alter generation, write to application assets, trigger a revision, or affect approval/export.
- Gemini can score a batch through an explicit judge target. If it is missing or fails, deterministic results are still written and the affected judge fields show unavailable/error.
- Each lesson has dimension scores, feedback/issues, and deterministic diagnostics. The report preserves run/model provenance and states which usage fields were unavailable.
- No verdict, threshold, or workflow action is emitted. The team reviews findings and decides what to change.
- One captured run is enough to validate the benchmark plumbing and inspect this model's output. A comparison claim needs repeated generation runs per condition; use at least three or state that run-to-run variance is unknown.

This gives the team a benchmark for the current generator and a reusable format for future model runs. It is not evidence that Gemini agrees with SMEs or that any judge score is safe to automate.

## After the EY meeting: validation and experiments

### Evaluator alignment

Confirm who can label a blind sample, which dimensions EY cares about, what data can be sent to a hosted judge, and what failures matter most. Follow the gold-set, held-out agreement, and calibration process in [EVAL_FRAMEWORK_PLAN.md](EVAL_FRAMEWORK_PLAN.md). Until that check is complete, use judge scores to identify patterns for human review, not as definitive quality labels.

### Add generator arms when selected

Every generator should produce the same run-bundle schema. The run manifest identifies the exact provider/model/checkpoint, quantization, prompts, retrieval configuration, and runtime measurements. Keep generation and scoring separate. If the generator and judge are the same model family/run, configure a different judge or flag the result as self-judged and exclude it from independent comparisons.

The first implementation only captures the current Qwen 7B arm. Add Gemini or other frontier APIs and Qwen 30B after the meeting confirms which models to compare, availability, cost limits, hardware, and data handling. Report quality by dimension alongside calls, latency, and usage; do not call an arm better from one run.

### Controlled optimization directions

Use the benchmark as a loop: freeze a baseline, inspect the failures, choose one change, generate a new batch, and score that batch with the same rubric. Keep source set, brief, and held-out examples fixed. Start with changes that do not require training; only move to weight updates if the results justify their cost and EY agrees to that scope.

1. **Diagnose the Qwen 7B baseline.** Group weak lessons by failure type: missing or weak evidence, topic bleed, poor sequencing, unsuitable teaching level, slide density, quiz defects, or structured-output failures. Review representative examples with a human before deciding which part of the pipeline to change.
2. **Try inference-time changes first.** For retrieval, compare one retrieval/evidence-packing change using a frozen retrieval question set and evidence trace. For prompts/templates, change one version at a time while keeping the model and evidence fixed. These change what the model sees or is asked to do; they do not update model weights.
3. **Compare generator arms.** Generate the same benchmark inputs with the current local model, a selected Gemini/frontier model, and later Qwen 30B if access and hardware permit. Store each as the same run-bundle format and score them with an independent judge or human review. This shows whether the better result comes from the model or from the shared pipeline.
4. **Test critique inside the generation loop as a separate workflow experiment.** Compare single-pass generation with draft → critic feedback → bounded local revision. Choose the intervention point explicitly: after plan generation, after each lesson, or after the full course. Start with one point, not all of them. Record first-draft and revised scores, which issues were fixed or introduced, and the extra model calls, time, and usage. The critic's feedback may guide revision in this experiment, but the benchmark scorer still only reports results and does not make decisions.
5. **Test quantization for efficiency.** Hold checkpoint, prompts, retrieval, and workflow constant while changing quantization. Report quality alongside latency and peak RAM/VRAM; quantization is a deployment/efficiency trade-off, not a way to add new knowledge.
6. **Consider Gemini-generated training examples only if simpler changes are insufficient.** Gemini can act as a teacher that produces source-grounded demonstrations, alternative explanations, or critique/revision pairs. Those text examples do not update Qwen weights by themselves. To change Qwen's weights, curate and filter the examples, then run a separate local training job such as supervised fine-tuning with a LoRA or Q-LoRA adapter. With text-only teacher outputs, describe this as teacher-generated synthetic-data fine-tuning or black-box distillation; logit-level distillation would require teacher probability/logit access. Keep the benchmark holdout out of prompt tuning and training, check synthetic examples against source evidence, and report training data, compute, adapter, and checkpoint provenance.
7. **Leave room for EY-suggested methods.** Add another method only as a named experimental condition with a hypothesis, a frozen comparison, and the same outcome measures. If EY suggests preference tuning, for example, it needs reliable preferred/rejected examples and a separate scope/compute check.

The current project brief and roadmap say training/fine-tuning is not a deliverable. Therefore step 6 and other weight-update methods remain conditional research options requiring explicit scope agreement, data rights, usable training examples, and suitable compute. Official Qwen recipes document LoRA and Q-LoRA as ways to adapt Qwen with fewer trainable parameters, while the practical memory requirement depends on model and setup ([Qwen fine-tuning guide](https://github.com/QwenLM/Qwen/blob/main/recipes/finetune/deepspeed/readme.md)). Research on teacher-generated synthetic data likewise treats it as training data for a student model and emphasizes task-specific evaluation ([teacher–student distillation study](https://arxiv.org/abs/2410.18588)). These references establish candidate methods, not a commitment or a prediction that they will improve this project.

## Decisions to leave the EY meeting with

- Can EY provide subject-matter experts for a small blind labeling exercise, and who owns the source material?
- Which quality dimensions and failure cases matter most, and what evidence would make EY trust the evaluator?
- Which documents may be used with hosted models? The first external-judge run remains limited to public or fictional sources.
- Is the main comparison a model swap (frontier versus local Qwen), and which local checkpoint/deployment constraint should be the target?
- Which experiment should come first: retrieval, prompts/templates, critique and revision, or quantization? What quality, latency, and hardware trade-offs are acceptable?
- Should any later critique experiment score only the finished course, or intervene after the plan, each lesson, or another generation step?
- Is lightweight fine-tuning allowed by project scope, data rights, and available compute? The current brief says it is not a deliverable, so this needs an explicit decision before training work.

## Order and verification

1. Agree on the run-bundle and score-record schemas and keep the first input corpus fictional/public.
2. Implement deterministic checks and explicit judge targeting in parallel; prepare runner capture of generated assets and evidence references.
3. Capture one Qwen 7B course run, run the batch scorer against it, then inspect the saved inputs and outputs for completeness.
4. Verify the judge JSON response format with one score call before scoring the full batch. If Gemini rejects the current JSON-object format, adapt only the judge request format.
5. Exercise missing-judge and judge-error paths; confirm the batch still writes deterministic findings for every lesson.
6. Do not compare optimization variants until the run bundle and rubric are frozen. Repeat each generation condition at least three times for a quality claim.

## Explicitly out of scope for this slice

- Any action on evaluated output: revision, approval changes, escalation, or export blocking.
- Real-time evaluation while lessons are being generated; scores are produced by a separate batch command.
- Saving benchmark scores in application database fields, changing the lesson API, or adding instructor UI.
- SME agreement claims, calibrated thresholds, or a trusted leaderboard before the human-alignment stage.
- Course-plan evaluation, multi-arm orchestration, Qwen 30B serving, or frontier-versus-local claims in the initial Qwen 7B benchmark.
- Prompt, retrieval, generation, quiz-validation, quantization, or fine-tuning changes in the benchmark implementation itself.
- Sending confidential EY documents to an external model API.
