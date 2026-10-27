# Implementation tooling research for evaluation execution

This document compares software for running evaluations. For the project's educational content quality criteria and the current recommendation, start with [course content quality framework research](FRAMEWORK_RESEARCH.md). The tooling selection below does not establish which educational qualities should be assessed.

Research date: 21 October 2026. Repository inspected: `24303e9` (`working MVP of document-to-course generation`).

**Recommendation: pilot Pydantic Evals as the primary evaluation harness, with DeepEval as the strongest alternative.** Keep evaluation criteria and pass/revise/escalate policy in application-owned Python code. Consider Ragas later for retrieval diagnostics and Learning Commons Evaluators as a source of educational rubrics. This recommendation reflects compatibility with this repository and current upstream documentation; it has not been validated by running these frameworks against the local model.

**What this project needs**

The implemented pipeline produces an approved plan, lesson slides and speaker notes, quizzes, and PPTX/SCORM exports. Its evaluation layer needs to assess those artifacts against their sources and the course brief. The current stack is Python 3.12/FastAPI, Pydantic, PostgreSQL/pgvector, local BGE-M3 embeddings, and an OpenAI-compatible endpoint serving Qwen 2.5 7B through Ollama. vLLM is an optional GPU path. Local/offline operation is a project requirement. See the [application README](../../README.md), [model configuration](../../apps/api/app/config.py), and [model-serving guide](../../services/inference/README.md).

Three requirements dominate the selection:

- **Grounding:** factual claims must be supported by the particular passages cited. Citation existence and citation coverage are separate from factual support.
- **Coherence:** lessons must follow the plan, avoid unintended topic duplication, and sequence prerequisites sensibly. The recorded baseline had repeated incident-reporting material and duplicated quiz questions across lessons despite valid citation IDs.
- **Pedagogy:** content and assessments must address the intended objectives, cognitive level, audience, examples, and practice. These require project-specific rubrics and instructor calibration.

The [existing evaluation plan](README.md) also requires repeatable comparisons of single-pass generation, fixed critique/revision, and bounded gated workflows, plus human review effort and runtime measurements. These assess generated content quality. Claims about actual learning gains would additionally require learner outcome evidence.

**Framework comparison**

The fit judgments below assume embedded Python evaluation, offline execution, and a small team delivering the existing project scope.

| Candidate | License | Relevant capabilities | Fit and integration tradeoff |
|---|---|---|---|
| [Pydantic Evals](https://github.com/pydantic/pydantic-ai/tree/main/pydantic_evals) | [MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE) | Typed cases/datasets, custom Python evaluators, LLM judges, numeric scores and reasons, local reports. | **Best initial fit.** Backend already pins Pydantic AI and has custom scoring prompts. Wrap the existing checks and guarded judge calls. Educational metrics and review policy remain ours. |
| [DeepEval](https://github.com/confident-ai/deepeval) | [Apache-2.0](https://github.com/confident-ai/deepeval/blob/main/LICENSE.md) | G-Eval custom rubrics, conditional DAG metrics, faithfulness and retrieval metrics, pytest/CLI integration, local model support. | **Strongest alternative.** Prefer if ready-made metrics save more work than adapting its test-case and model abstractions. Requires explicit local/telemetry configuration. |
| [Ragas](https://github.com/vibrantlabsai/ragas) | [Apache-2.0](https://github.com/vibrantlabsai/ragas/blob/main/LICENSE) | Faithfulness, context precision/recall, general-purpose and custom rubric metrics, datasets and experiments. | **Useful retrieval specialist.** Can assess broader applications, but its particular value here is diagnosing retrieval and grounding. Additional LangChain-related dependencies and data adapters need assessment. |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | [MIT](https://github.com/promptfoo/promptfoo/blob/main/LICENSE) | YAML test cases, JSON Schema and code assertions, LLM rubrics, provider comparisons, CI and local reports. | **Good separate regression runner.** Python bridge and local providers can test the full pipeline. Adds a Node runtime and is less natural inside the Python worker. |
| [TruLens](https://github.com/truera/trulens) | [MIT](https://github.com/truera/trulens/blob/main/LICENSE) | RAG metrics, custom evaluators, component selectors, local providers, batch evaluation and tracing. | **Consider when component-level trace analysis becomes a priority.** More recording/selector concepts than the initial course harness needs. |
| [Learning Commons Evaluators](https://github.com/learning-commons-org/evaluators) | [MIT code; CC BY 4.0 prompts/content](https://github.com/learning-commons-org/evaluators/blob/main/LICENSE.md) | Educational rubrics for text complexity, clarity, feedback, standards alignment and critical thinking. | **Rubric resource.** Adapt selected criteria to adult workplace learning; it is not a complete course-gating system. Examples use external model API keys, so local inference requires adaptation. Some included datasets have separate noncommercial licenses. |
| [Arize Phoenix](https://github.com/Arize-ai/phoenix) | [Elastic License 2.0, including phoenix-evals](https://github.com/Arize-ai/phoenix/blob/main/packages/phoenix-evals/LICENSE) | Standalone Python evaluators, datasets/experiments, custom rubrics and extensive tracing. | **Optional later platform.** Its current license differs from permissive open-source candidates. Free internal self-hosting is supported; hosted-service restrictions are described in its [license guidance](https://github.com/Arize-ai/phoenix/blob/main/docs/phoenix/self-hosting/license.mdx). |

Pydantic Evals supports code-defined experiments and reports saved to disk; Logfire is an optional visualization service. Its [custom evaluator interface](https://pydantic.dev/docs/ai/evals/evaluators/custom/) can call existing validators and judge functions. [LLMJudge](https://pydantic.dev/docs/ai/evals/evaluators/llm-judge/) supports custom rubrics and explicit model selection. These capabilities suit the current structured course artifacts without requiring a generation rewrite.

DeepEval's [G-Eval](https://deepeval.com/docs/metrics-llm-evals) and [faithfulness metric](https://deepeval.com/docs/metrics-faithfulness) provide a broader ready-made metric suite. Ordinary local vLLM serving has a documented [LocalModel integration](https://deepeval.com/integrations/models/vllm); a custom model wrapper is only needed when its default behavior does not meet application needs. Its [pytest and CI workflow](https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd) is an advantage for regression gates.

Ragas supports [custom rubrics](https://docs.ragas.io/en/v0.4.1/concepts/metrics/available_metrics/rubrics_based/) as well as [faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/). Local models, embeddings, and datasets are supported, so it is a viable candidate. Its [current dependencies](https://github.com/vibrantlabsai/ragas/blob/main/pyproject.toml) and evolving metric APIs should be checked against this repository's constraints. The older `explodinggradients/ragas` URL redirects to its current organization.

Promptfoo supports a [Python provider](https://www.promptfoo.dev/docs/providers/python/), [vLLM](https://www.promptfoo.dev/docs/providers/vllm/), and [LLM rubric assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/llm-rubric/). TruLens supports [custom metrics](https://www.trulens.org/component_guides/evaluation/feedback_implementations/custom_feedback_functions/) and [batch evaluation](https://www.trulens.org/reference/trulens/core/batch/). These are credible alternatives, with different emphasis on CLI experiments and component tracing respectively.

Learning Commons' [repository catalog](https://github.com/learning-commons-org/evaluators#available-evaluators) is useful for rubric design. Its [local setup instructions](https://github.com/learning-commons-org/evaluators/blob/main/docs/setup-windows.md) still require provider keys: running a notebook locally does not by itself make inference offline. Grade-level and school-standard rubrics need adaptation and validation for EY's audience.

**Why Pydantic Evals comes first here**

The backend already has the inputs a custom evaluator needs: source evidence, structured content, objectives, audience, and versioned prompts. [critique/service.py](../../apps/api/app/core/generation/critique/service.py) produces grounding, coherence and pedagogy feedback; [Asset](../../apps/api/app/models/asset.py) already has score fields and critique JSON. The evaluation jobs are still stubs in [handlers.py](../../services/worker/handlers.py). A harness that reuses these parts is likely the shortest route to a useful experiment.

There are two material integration conditions:

1. **Preserve the guarded model client.** The existing `chat_structured` checks the context budget on every attempt and records model calls. `get_pydantic_ai_model()` does not inherit those checks. Stock framework clients can bypass them too. Start with a custom evaluator that calls the existing guarded judge function, or deliberately reproduce its guards and accounting in a model adapter. Extend the current critique input contract to include the approved plan and other-lesson summaries alongside the exact evidence; those fields are not currently passed to the helper.
2. **Align versions.** `constraints.txt` pins `pydantic-ai-slim==2.42.0`. The [Pydantic Evals v2.42.0 package](https://raw.githubusercontent.com/pydantic/pydantic-ai/v2.42.0/pydantic_evals/pyproject.toml) requires the matching slim version; `pydantic-evals==2.42.0` is the first compatibility candidate. Its [tagged evaluator implementation](https://raw.githubusercontent.com/pydantic/pydantic-ai/v2.42.0/pydantic_evals/pydantic_evals/evaluators/common.py) includes LLMJudge and simplified G-Eval. Confirm dependency resolution against the complete constraints before adopting it.

Pydantic's [standard metric recipes](https://pydantic.dev/docs/ai/evals/evaluators/standard-quality-metrics/) explicitly distinguish rubric approximations from upstream algorithms. A rubric named faithfulness is not automatically equivalent to Ragas or DeepEval's implementation. If published-method parity is required, use the actual upstream metric through an adapter and record its version.

**Proposed evaluation design**

| Level | Checks | Method |
|---|---|---|
| Plan | Objective IDs resolve; planned duration fits the brief; source coverage; sensible ordering. | Deterministic references and totals, then a calibrated rubric for coverage and sequencing. |
| Claim/citation | Citation points to an existing project source; cited passage supports the specific claim; important claims are cited. | Code checks for identifiers/provenance, then claim-to-cited-passage support evaluation. |
| Lesson | Objective coverage, explanations, examples, practice, language and cognitive level. | Separate anchored educational rubrics with reasons and affected block IDs. |
| Quiz | Valid key/options; source reference and span agree; correct answer/explanation; plausible distractors; objective alignment. | Code validation first, then semantic and pedagogical checks. Add and preserve objective IDs in quiz schemas/results before enforcing item-to-objective links in code. |
| Whole course | Repeated questions, misplaced topics, inconsistent terminology, gaps and prerequisites. | Exact/semantic duplicate candidates plus review against the full plan and lesson summaries. Intentional recap must be allowed. |
| Export | Readable slides, overflow, working links and SCORM behavior. | Artifact rendering and player checks with human inspection where needed. Text scores alone cannot establish visual usability. |

Return named metric results with score, reasons, evidence/block IDs, and failure status. Compute policy in code: deterministic hard failures cannot be overridden by an average score; quality failures can request bounded revision; exhausted budgets, missing evidence and evaluation errors escalate. Calibrate thresholds using instructor-labelled examples. The existing summary prompt's `<4` revision rule is a scaffold, not an established threshold.

The baseline exposes two application validation gaps to address during integration: slide citation statistics do not enforce factual support, and quiz source-span validation currently searches the combined context rather than only the declared reference. Factual support needs semantic evaluation; identifier and span-to-reference checks can be deterministic. See [lesson/service.py](../../apps/api/app/core/generation/lesson/service.py) and [quiz/service.py](../../apps/api/app/core/generation/quiz/service.py). A framework will not repair these application-specific rules automatically.

Preserve every evaluation attempt with the source text/hash, drafting evidence, course/model/prompt/rubric versions, Git SHA, configuration, scores, errors, calls, latency and available token/memory measurements. The current mutable `Asset.critique` can show the latest result, but experiment history needs separate immutable records. Keep the single-pass baseline available as an experimental arm.

**A focused pilot before committing to integration**

Evaluate one existing lesson and controlled variants using the same frozen evidence, rubric, local judge and instructor labels in Pydantic Evals and DeepEval. Include surrounding lesson summaries so cross-course defects are observable.

- Add a nonexistent citation, a valid quote attached to the wrong reference, a contradictory claim, an invalid objective ID, a duplicate quiz question, and an unrelated topic copied from another lesson. Include clean content and an intentional recap as controls.
- Require hard code-check failures to prevent `pass`. Compare semantic defect detection and false positives with blinded instructor review. Valid JSON is only an operational check.
- Run with external networking unavailable, local judging configured explicitly, and hosted tracing disabled. Force an oversized prompt and a malformed response; errors must be recorded and cannot become passing scores. Preserve the context guard on retries.
- Start with judge concurrency one on CPU. Record implementation effort, calls, retries, elapsed time and memory. The repo's recorded baseline took 27 minutes on one CPU laptop; that is historical project evidence, not a new measurement on this clone.
- Exercise pass/revise/escalate with a fixed revision budget. Save all attempts. Use pilot agreement to refine the rubric; conduct the larger planned instructor study before treating it as validated evaluation.

Prefer Pydantic if it gives useful reports and preserves the existing checks with less work. Prefer DeepEval if its metrics yield materially better defect detection, instructor agreement, or delivery effort under the same conditions. Add Ragas only when retrieval experiments need its specific methods.

**Offline settings and judge validity**

Configure every judge and embedding endpoint explicitly. Pydantic's tagged LLMJudge has a hosted default when a model is omitted. For DeepEval, disable telemetry with `DEEPEVAL_TELEMETRY_OPT_OUT=1` and use local models/embeddings without hosted reporting; see [privacy settings](https://deepeval.com/docs/data-privacy). Ragas documents its telemetry switch in [analytics code](https://github.com/vibrantlabsai/ragas/blob/main/src/ragas/_analytics.py): `RAGAS_DO_NOT_TRACK=true`. Promptfoo also has [telemetry controls](https://www.promptfoo.dev/docs/configuration/telemetry/). Verify offline behavior for the pinned version after preparing dependencies and model files.

A local 7B model judging its own output can share the generator's blind spots. Configure the judge independently, use a stronger or different local model where resources permit, blind workflow identities, and compare with instructors. Repeat borderline cases and report failed judgments and variability. The [MT-Bench judge study](https://arxiv.org/abs/2306.05685) identifies position, verbosity and self-enhancement biases; changing model families alone does not establish reliability.

**Maintenance signals checked**

| Project | Observed upstream signal | Source |
|---|---|---|
| Pydantic AI / Evals | Release title v2.59.0 dated 20 Oct 2026; repository already pins v2.42.0. | [Releases](https://github.com/pydantic/pydantic-ai/releases) |
| DeepEval | GitHub latest release python-v4.2.4 published 22 Sep 2026; main commit 19 Oct 2026. | [Release](https://github.com/confident-ai/deepeval/releases/tag/python-v4.2.4), [commit](https://github.com/confident-ai/deepeval/commit/727203702cddf68e4f01a6ef95b23d9cb9036654) |
| Ragas | GitHub latest release v0.4.3 published 13 Jan 2026; main commit 24 Feb 2026. | [Releases](https://github.com/vibrantlabsai/ragas/releases), [commit](https://github.com/vibrantlabsai/ragas/commit/298b68274234c060deacab3cf5fb52aa3a20e885) |
| Promptfoo | Release 0.124.1 dated 8 Oct 2026. | [Releases](https://github.com/promptfoo/promptfoo/releases) |
| TruLens | Release 2.16.0 dated 19 Oct 2026. | [Releases](https://github.com/truera/trulens/releases) |
| Phoenix | Core 20.23.0 dated 16 Oct 2026; evals 3.9.2 dated 9 Oct 2026. | [Releases](https://github.com/Arize-ai/phoenix/releases) |

These signals support dependency-maintenance assessment; they do not establish metric quality or latest PyPI versions. Pin and test the selected package version. Framework installation, local-model scoring, and runtime benchmarking remain the proposed pilot work.
