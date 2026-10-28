# Workflow evaluation

The original workflow study compares workflows using pretrained local models and does not require fine-tuning. A separate reviewer-training experiment following the team's GPU access is described below. Start baseline collection in [sprint 1](../../docs/SPRINT_01.md); do not postpone evaluation until the final month.

## Sprint 1

The assigned owner will add:

- A manifest of 3-5 public documents with origins and reuse permissions.
- Thirty labelled retrieval questions with expected source passages.
- A command that records recall@5 and per-query retrieval time.
- Model/server configuration, machine specifications and structured-output/tool-call results.
- A repeatable offline/restart check and a short failure analysis.

The application smoke script is an operational check, not a quality benchmark. This directory currently contains the evaluation design; the benchmark runner remains to be implemented.

The [course content quality framework research](FRAMEWORK_RESEARCH.md), researched on 21 October 2026, compares LORI/LOEP, Anthropic/Learning Commons instructional rubrics, Learning Commons Evaluators, OSCQR and specialist research projects. It proposes criteria for comprehensiveness, instructional quality and learning alignment. A separate [implementation tooling comparison](IMPLEMENTATION_TOOLING_RESEARCH.md) covers software for executing those checks.

Following the team's GPU access, the [proposed reviewer training experiment](TRAINING_PLAN.md), prepared on 25 October 2026, describes Qwen model candidates, data preparation, supervised adapter training, validation and later integration. The supplied NTU guide confirms H200 compute resources and PBS submission. The plan uses the team's reported `gpu_free` queue and its four-hour job limit, beginning with a resumable 9B pilot before a 27B LoRA experiment; live project limits and storage still need inspection. No training run has been launched.

The current experiment assumes no capacity for in-house dataset labelling. It uses public Prometheus, RAGTruth, LecEval and Oak MCQ annotations, with held-out task-specific evaluation. Whole-course comprehensiveness remains a provisional source-coverage judgment. The trained reviewer provides advisory authoring feedback; the free queue supports scheduled review batches rather than an assumed permanent inference endpoint.

For the teammate carrying out the experiment, start with the standalone [evaluator training handoff](TRAINING_HANDOFF.md), prepared on 27 October 2026. It covers project context, the reason for training, agreed constraints, execution order, GPU workflow, integration expectations and required deliverables.

The runnable pipeline for that experiment is in [training/](training/README.md): data preparation, resumable MS-SWIFT LoRA training for the four-hour queue, evaluation and batch inference. It was checked on CPU on 27 October 2026; no GPU job has run yet.

## Later comparisons

Hold the model, sources and rubric fixed across single-pass generation, fixed critique/revision and a bounded agent workflow. Repeat runs and report variability, failures and review effort.

| Dimension | Evidence |
|---|---|
| Grounding | Exact citation validity, unsupported-claim count and human source checks |
| Coverage and teaching quality | Objective/source coverage plus human rubric |
| Visual usability | Rendered slide checks and human readability review |
| Reviewer effort | Edits, rejected assets and review time |
| Efficiency | Wall-clock time, model/tool calls, token counts where available |
| Hardware | Peak RAM/VRAM and artifact storage |
| Reliability | Valid structured output, successful resume, failure/retry counts |

Save small, non-sensitive raw results with configuration hashes and the Git commit. Keep large model files and generated assets outside Git.
