# Workflow evaluation

The revised research deliverable compares workflows using pretrained local models. No training or fine-tuning is required. Start baseline collection in [sprint 1](../../docs/SPRINT_01.md); do not postpone evaluation until the final month.

## Sprint 1

The assigned owner will add:

- A manifest of 3-5 public documents with origins and reuse permissions.
- Thirty labelled retrieval questions with expected source passages.
- A command that records recall@5 and per-query retrieval time.
- Model/server configuration, machine specifications and structured-output/tool-call results.
- A repeatable offline/restart check and a short failure analysis.

The application smoke script is an operational check, not a quality benchmark. This directory currently contains the evaluation design; the benchmark runner remains to be implemented.

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