# Evaluator model training handoff

**Prepared:** 27 October 2026, Asia/Singapore  
**Audience:** The teammate implementing and running model training  
**Repository:** <https://github.com/deyanyanyan/EYxNTU>  
**Application revision inspected:** `24303e971c6389f6f923b3f5a6da10c5830d5a00`  
**Status:** Proposed experiment ready for pilot implementation. No training scripts, trained adapters or GPU runs have been produced in this work.

## 1. Your assignment

Build a reproducible experiment that adapts an open-weight Qwen model to review educational content. Deliver the data preparation, training, checkpoint/resume, evaluation and inference artifacts needed for another teammate to reproduce your results and integrate the selected reviewer into the LMS.

Start with **`Qwen/Qwen3.5-9B` for the pilot**. Use **`Qwen/Qwen3.8-27B` as the main candidate** after the pilot and memory profiling. Use supervised LoRA adaptation with existing public annotations. There is no budget for the team to label a new dataset.

The first milestone is a small working public-data pipeline with a demonstrated save/stop/resume cycle and prompted baseline results. A large training run comes after that evidence. The assignment ends with a reproducible model recommendation and an inference interface; production UI and LMS deployment are subsequent integration tasks.

This document is standalone. The longer [training plan](TRAINING_PLAN.md) and [content-framework research](FRAMEWORK_RESEARCH.md) provide supporting detail. This GPU experiment is a later extension to the original pretrained-model baseline described in older project documents.

## 2. What the project does

EYxNTU is an LLM-assisted course-authoring platform for professional learning. A course author supplies documents and a learner brief: audience, goals and intended duration. The system retrieves source evidence and generates learning objectives, a syllabus, lesson slides with speaker notes, and quizzes. The author can approve the plan and export the material as PPTX or a SCORM package for an LMS.

The current flow is:

```text
Upload sources -> ingest/retrieve -> generate objectives and syllabus
    -> author approves plan -> generate slides, notes and quizzes
    -> export PPTX / SCORM
```

The intended contribution is an evaluation layer that checks whether the generated material is accurate, coherent, adequately teaches the intended content and supports the learning objectives. Generating a plausible course is already possible; establishing and improving its content quality is the problem we are addressing.

The application uses a Python/FastAPI backend, PostgreSQL with pgvector, a PostgreSQL-backed worker and a Next.js authoring workbench. Its current default generation model is `qwen2.5:7b-instruct` served through Ollama. Preserve that generator as the baseline while testing the new reviewer.

### Why the existing checks are insufficient

The historical baseline in [the project handoff](../../docs/HANDOFF.md) produced a complete course, but reading the material exposed topic bleed and repeated quiz questions. Valid citations and successful export did not identify those instructional weaknesses.

The current plan's `coverage` metric counts references to excerpts offered during planning. It does not establish that the finished course adequately teaches all required material. Quiz validation catches selected structural/evidence problems, but does not establish whether questions meaningfully assess the intended learning.

## 3. Why we are training an evaluator

We want a reusable reviewer that follows explicit criteria, checks generated claims against evidence and produces actionable findings. Fine-tuning is an experiment to determine whether adaptation improves these abilities beyond prompting the original model.

| Intended capability | Example question |
|---|---|
| Source grounding | Does this explanation introduce an unsupported rule or contradict its source? |
| Instructional presentation | Do the slide and explanation agree, communicate clearly and follow a sensible structure? |
| Assessment quality | Are distractors plausible, or is the correct option obvious from its wording? |
| Coverage and alignment | Are identified source requirements taught, and do the teaching and assessments support the objectives? |

Public datasets directly supervise the first three areas to varying degrees. **They do not provide complete adult-course coverage, depth or objective-alignment supervision.** Those broader judgments will initially use source-conditioned rubric prompts and must remain advisory.

Train on reviewer outputs: existing scores, feedback or annotated error spans. Candidate course content is an input to review. Do not substitute a course-generation objective for the evaluator objective.

The model learns reviewing behaviour; each new course supplies its own source evidence at inference time. There is no need to fine-tune again for each upload. Static content review also cannot establish actual comprehension, retention or workplace transfer without learner evidence.

## 4. Agreed constraints and scope

- **No in-house dataset labelling:** use published annotations and mechanically derived formats. A new expert-annotation exercise or paid teacher-model labelling pipeline is outside this assignment.
- **Public-only training materials:** the supplied NTU guide's login banner says the cluster can store/process open data only. This applies to inference inputs too. Private workplace documents need a hosting environment that permits them.
- **Working allocation:** NTU GaaS, PBS, `gpu_free`, maximum **four hours per job**, based on the guide and the teammate's reported workflow. Verify project membership, resource limits and storage on the actual account.
- **Separate training environment:** the application's API/worker image installs CPU PyTorch. Create a pinned CUDA training environment on the cluster; training does not require starting the LMS database or frontend.
- **Preserve the baseline:** use separate reviewer model configuration and artifacts. Existing generation behaviour remains the comparison arm.
- **Advisory educational judgments:** public benchmark agreement does not establish calibrated adult-course quality. Automatic approval thresholds and claims of learning gains are outside the evidence currently available.

## 5. Datasets and how to use them

Research below was checked on 25 October 2026. Confirm revisions, access and terms when acquiring files; record them in the manifest.

| Dataset | Available supervision | Role in this experiment |
|---|---|---|
| [Prometheus Feedback Collection](https://huggingface.co/datasets/prometheus-eval/Feedback-Collection) | 99,952 examples with instruction, response, reference answer, rubric, feedback and 1-5 score. GPT-4-generated labels; card declares CC BY 4.0. | Main rubric-following/feedback training foundation. Preserve the reference input and original scoring anchors. These are synthetic general-response judgments. |
| [RAGTruth](https://github.com/ParticleMedia/RAGTruth) | Nearly 18,000 generated responses with source context and human-marked hallucination spans/types. MIT repository; underlying source corpora have their own terms. | Teach source-grounding review. Join response and source records correctly. Preserve `implicit_true` information: unsupported by a source is different from proven false. |
| [LecEval](https://github.com/JoylimJY/LecEval/tree/main/dataset) | 2,097 slide/transcript pairs with human ratings for relevance, clarity, structure and engagement. MIT repository; separate original lecture-asset rights were not verified. | Closest instructional-presentation adaptation. Supply slide images and transcripts. Its score-only supervision does not include expert critique rationales. Confirm permitted reuse of the lecture assets before training. |
| [Oak MCQ MinDiff](https://github.com/oaknational/oak-dspy-mcq-eval) | 311 teacher-scored MCQs with correct answers and distractors. Data is OGL v3.0; code MIT. | Initially a distractor-quality benchmark and prompt-selection dataset. Use `human_score`, not included baseline model scores. The code supplies a reproducible 61 demonstration / 185 development / 65 test split. Preserve the test set. |

**Optional:** [SciEval](https://github.com/SciEval-Benchmark/SciEval) is closer to lesson-level pedagogy review: authors report 273 K-12 science lesson materials and 3,549 criterion annotations with evidence/advice. It remains request-only. Start without it; add a documented experiment if access is obtained. Its score 0 means not applicable, not worst quality.

Learning Commons CLEAR annotations are an optional readability task, with a grades 3-4 audience and CC BY-NC-SA terms. General QA sets, Bloom-level classifications and collections of good lessons do not automatically provide course-quality labels. Keep these outside the first training mixture.

### Data preparation requirements

1. Save dataset revisions, file checksums, original row IDs, label origin, licence/attribution, grouping keys and split assignments.
2. Split before training, prompt tuning or augmentation. Group Prometheus by original instruction; audit RAGTruth's official partitions for shared sources; split LecEval by lecture; keep duplicate/related Oak questions together. Keep the test partitions untouched until the chosen comparison is ready.
3. Use only the labels that exist. Prometheus provides feedback and scores; RAGTruth provides annotated spans/types; LecEval and Oak provide ratings. Do not fabricate expert rationales or source citations for score-only records.
4. Preserve each rubric and scale. A slide-engagement score, distractor-quality score and grounding label are separate tasks. They must not become interchangeable overall quality scores.
5. Start with a bounded public subset selected using measured throughput. Record the selection. Use task-balanced sampling/replay when adding educational tasks so the larger general dataset does not overwhelm them.

## 6. Model and training configuration

| Item | Starting decision |
|---|---|
| Pilot checkpoint | [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) |
| Main candidate | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) |
| Method | Supervised LoRA; profile BF16 first, supported 4-bit QLoRA if memory requires it |
| Training library | [MS-SWIFT, dense-model Transformers recipe](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/BestPractices/Qwen3_8-Best-Practice.md) |
| Initial device request | One allocated H200; verify actual memory with `nvidia-smi` |
| Initial parameters | Rank 16 or 32; learning rate around `1e-4`; microbatch 1 with gradient accumulation; gradient checkpointing |
| Length and duration | Profile text cases at 4K, then 8K input-plus-output tokens where needed; select total steps/epochs from development results and budget |

These are experimental starting points, not measured optimal settings or a promise that 27B fits a particular context/batch on one GPU. Use the original Hugging Face post-trained checkpoints and pin revisions. Ollama tags, GGUF files and inference-only quantized exports are not the training checkpoints.

Current MS-SWIFT documentation explicitly supports these model families. Qwen3.5 uses `qwen3_5`; Qwen3.8 uses the dedicated `qwen3_8` template. Pin the working MS-SWIFT, Transformers, PyTorch, PEFT, CUDA and attention-kernel combination rather than installing an unrecorded moving environment.

Use language adapters with vision components frozen initially; inspect the actual trainable-parameter names/count. For the text-only pilot, use Prometheus/RAGTruth. LecEval requires a separately profiled multimodal stage with its images, even with a frozen vision encoder.

Use concise final review outputs. Follow the recipe's non-thinking SFT handling: current MS-SWIFT documents `add_non_thinking_prefix` for training, whereas `enable_thinking` controls inference. Inspect rendered examples and loss masks; do not assume disabling thinking at inference changes the training labels. Record explicit inference settings as well, because backend defaults differ.

Preserve all decisive source evidence and targets in tokenized examples. If a requirement and its relevant teaching material do not fit, create scoped review cases with tracked coverage. Silent truncation would make a completeness judgment invalid.

## 7. NTU GaaS workflow

The [NTU quick-start guide](https://entuedu.sharepoint.com/teams/ntuhpcusersgroup2/SitePages/Quick-Start-Guide-on-using-GaaS-Resource.aspx), supplied as a PDF captured on 25 October, describes H200 compute resources and **PBS**, with templates under `/usr/local/templates/`. Cluster totals are not the team's GPU allocation. The account's project code, permitted GPU count, persistent paths and quotas still need to be inspected.

```bash
# Use your NTU ID; institutional VPN is required off campus.
ssh YOUR_NTU_ID@gaas.hpc.ntu.edu.sg

# Inspect live project, quota, queue and template information.
menu.sh
qstat -Q
pbsnodes -aSj
ls -l /usr/local/templates/*.pbs
module avail
```

Copy an appropriate local template and preserve its cluster-specific setup. The initial resource fields should target:

```text
#PBS -N course-evaluator-pilot
#PBS -P REPLACE_WITH_ASSIGNED_PROJECT_CODE
#PBS -q gpu_free
#PBS -l select=1:ncpus=4:ngpus=1
#PBS -l walltime=04:00:00
```

This block specifies proposed resources only. Add the template's required host-memory settings, environment activation, working directory and actual training command before submitting. Use your assigned project code. The guide has inconsistent annual/paid example queue names and an administrator-project example; those do not replace the free queue/project specified for this experiment.

The guide lists Anaconda 2025 and CUDA 13.0 modules. Check actual compatibility with the driver, PyTorch and required kernels. Run training, GPU tests and inference benchmarks in scheduled compute allocations. The login node's GPU is not permission to run training there.

```bash
# Once the completed script has been checked:
qsub training_job.pbs
qstat -u "$USER"
qstat -f JOB_ID
```

### Four-hour checkpoint/resume requirement

Implement and test a trainer-side elapsed-time stop callback or equivalent measured cutoff. It must checkpoint and exit before PBS terminates the job. Initially budget about 20 minutes for final saving, and aim for checkpoints approximately every 10-15 minutes; adjust both using actual save times.

Store checkpoints on verified persistent storage. A resumable checkpoint needs adapter weights, optimizer, scheduler, trainer/global-step and RNG state; a serving adapter export is a separate artifact. Keep the same dataset, preprocessing, experiment-wide training schedule and warm-up across jobs. Do not reset the training schedule with each PBS submission.

Before a main run, prove that a stopped job resumes at the expected global step with intact optimizer/scheduler state, can perform another update and produces a loadable adapter. Profile model download/staging, startup and checkpoint overhead within the total walltime budget.

## 8. Execution order and evaluation

| Step | Work | Evidence to produce |
|---|---|---|
| 1. Establish access | Inspect project, queue, allocated hardware, storage and software. | Recorded environment and permitted resource request; no assumed paths or quotas. |
| 2. Prepare public data | Implement acquisition, deterministic transformations and grouped splits. | Manifest, checksums, task examples, licence notes, split-leakage checks and rendered training targets. |
| 3. Establish baselines | Run prompted 9B and 27B on the same development cases. Include an existing rubric reviewer if practical. | Per-task predictions, metrics, valid-output rate, inference configuration and runtime/memory. |
| 4. Demonstrate pilot | Train a small 9B adapter and test stop/resume/reload. | Complete checkpoints, resumed step/state, trainable-parameter audit, memory/throughput and smoke inference. |
| 5. Compare adaptations | Compare general rubric warm-up, grounding adaptation and educational-task additions on development data. | Controlled settings and per-task results showing gains/regressions. |
| 6. Run main candidate | Profile and adapt 27B if the preceding results and allocation justify it. | Reproducible run bundle, complete checkpoints and serving adapter. |
| 7. Final evaluation | Evaluate selected runs once on untouched test partitions. | Grouped uncertainty estimates, failure cases and a deployment recommendation. |

Report results separately:

- **Prometheus:** rubric-score agreement and valid output, explicitly labelled agreement with synthetic targets.
- **RAGTruth:** span/example-level detection precision, recall and F1 under a documented matching policy.
- **LecEval:** per-dimension agreement with human ratings, including the chosen multi-rater aggregation rule; retain lecture-level grouping.
- **Oak:** score error and agreement using human scores, preserving the test partition. Its small size limits conclusions.
- **Operational:** peak VRAM, throughput, checkpoint/save/reload time, inference latency and malformed output rate.

Use identical inputs and rubrics when comparing each base checkpoint with its adapter. Select configurations on development data. Keep critical regressions visible rather than hiding them in a single average. The selected result can be a smaller model or an untuned baseline if adaptation does not help.

Optional automatic regression cases can remove a known teaching block, corrupt an answer key or break a citation ID. These test controlled failure sensitivity; they are not expert labels for the quality of real courses. Without new project-specific labels, do not report adult-course expert agreement, comprehensiveness accuracy or learning gains.

## 9. How the LMS will use your model

The future authoring pipeline will extract a versioned requirements inventory from the complete source set, then review the generated plan, lessons and quizzes against it. The model will receive the learner brief, relevant requirements, full objectives, exact source passages and generated material. Visual judgments will additionally receive rendered slides.

The result should identify a criterion, issue/verdict, affected lesson/slide/question, supporting evidence and a suggested correction where available. Scores retain their rubric/scale. Unsupported fields must remain absent or explicitly unavailable rather than being invented. These richer LMS outputs are a proposed inference contract; public training datasets do not supply supervision for every field.

For example, a lesson may accurately teach a reporting deadline but omit the reporting channel. The reviewer should locate the missing requirement, show the relevant source passage and suggest adding the procedure. An automatically extracted inventory can itself miss requirements, so the UI should describe the result as **coverage of extracted requirements**.

Authors will see findings and can edit or request a bounded revision, followed by a new evaluation. Model scores do not automatically approve the course. Preserve evidence and content/model/rubric revisions so reports become stale when their material changes.

### Integration points the next implementer needs

| Existing location | Current state / future change |
|---|---|
| [Plan generation](../../apps/api/app/core/generation/plan/service.py) | Produces the syllabus/objectives; add source-inventory/plan review around it. Existing `coverage` is excerpt-reference coverage. |
| [Lesson generation](../../apps/api/app/core/generation/lesson/service.py) and [quiz generation](../../apps/api/app/core/generation/quiz/service.py) | Produce material to review. Preserve deterministic validation and add explicit quiz-to-objective links. |
| [Critique helper](../../apps/api/app/core/generation/critique/service.py) | Scaffolded grounding/coherence/pedagogy calls through the shared generation client; not connected to lesson generation. Needs richer inputs/results. |
| [Worker handlers](../../services/worker/handlers.py) | `CRITIQUE_ASSET` and `EVAL_RUN` remain unimplemented. These are candidate review-job hooks. |
| [Settings](../../apps/api/app/config.py) and [LLM client](../../apps/api/app/core/llm/client.py) | Add separate evaluator configuration; preserve context guards on every retry and model-call accounting. |
| [Asset model](../../apps/api/app/models/asset.py), [API schema](../../apps/api/app/schemas/course.py), [course panel](../../apps/web/components/course-panel.tsx) | Score/critique storage exists, but criterion-level reports and their UI are future work. |

The four-hour free queue supports scheduled inference batches, not an assumed continuously available endpoint. Supply a batch inference interface and documented output format first. A future backend should submit work, return, then poll/import reports; the current synchronous worker and 120-minute stale-job default cannot wait through PBS queueing plus a four-hour allocation. Continuous serving needs a suitable deployment allocation. Private course inputs must remain outside NTU batch jobs under the supplied open-data-only rule.

## 10. What to hand back

Use a dedicated training area such as `packages/eval/training/`; it does not exist yet. Keep large datasets, weights, checkpoints and generated outputs outside Git. A suggested local artifact root is `data/artifacts/evaluator-training/RUN_ID/`; choose a verified persistent equivalent on the cluster.

Deliver:

1. **Runnable code:** public-data preparation, training configuration/entrypoint, elapsed-time stop/resume support, benchmark runner and batch inference command.
2. **Reproducible setup:** pinned dependency environment, exact base-model/tokenizer/processor revisions, PBS template and tested commands with documented placeholders.
3. **Data record:** dataset revisions/checksums, licences/attribution, split manifests, transformations, group/deduplication rules and inspected target examples.
4. **Run artifacts:** configuration, seed, Git revision, dataset/rubric hashes, logs, losses, hardware/throughput, scheduler job IDs and complete resumable checkpoints.
5. **Serving artifact:** selected adapter, matching base revision, tokenizer/processor/template settings, explicit thinking setting, input/output contract and successful reload/inference example.
6. **Results report:** base-versus-adapted comparisons per task, uncertainty, failure cases, regressions, runtime costs, known limitations and the recommended next step.

The handback is complete when another teammate can reproduce data splits, run a baseline, train/resume the pilot, reload the delivered model and reproduce the reported comparison. A report that adaptation did not improve the baseline is a valid experimental outcome; an adapter file alone is insufficient.

### First actions

- [ ] Obtain the assigned NTU project code and inspect the live `gpu_free` entitlement and storage.
- [ ] Create the separate GPU environment and pin exact model/software revisions.
- [ ] Build the public-data manifest, grouped splits and a small text-only pilot subset.
- [ ] Inspect templates, tokenized examples, loss masks and trainable parameters.
- [ ] Record prompted baselines; demonstrate train/save/stop/resume/reload on 9B.
- [ ] Report the pilot evidence and resource estimate before scheduling the larger comparison.

At preparation time, the training/research Markdown files are uncommitted local additions. Share this handoff and the relevant documents with the recipient, or include them in the shared branch; cloning the application revision above alone will not retrieve them.

## References

- [Project README](../../README.md): application workflow and repository map.
- [Detailed training plan](TRAINING_PLAN.md): public-data experiment, NTU guide interpretation and deployment limits.
- [Content-quality research](FRAMEWORK_RESEARCH.md): proposed scorecard and comprehensiveness approach.
- [MS-SWIFT Qwen training recipes](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/BestPractices/Qwen3_8-Best-Practice.md): rechecked 27 October 2026; pin the version used in the experiment.
- [NTU GaaS guide](https://entuedu.sharepoint.com/teams/ntuhpcusersgroup2/SitePages/Quick-Start-Guide-on-using-GaaS-Resource.aspx): authenticated institutional reference; verify live account details.
- [Oak data/code licences](https://github.com/oaknational/oak-dspy-mcq-eval/blob/main/LICENSE.md): preserve the data attribution separately from the code licence.
