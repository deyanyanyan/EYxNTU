# Reviewer training pipeline (`evaltrain`)

Runnable implementation of the [training handoff](../TRAINING_HANDOFF.md): public-data preparation with grouped splits, MS-SWIFT LoRA training that checkpoints and resumes inside the four-hour `gpu_free` queue, prompted-baseline and adapter evaluation with grouped confidence intervals, and a batch inference command.

**Status, 27 October 2026, evening.** The 9B pilot has run on GaaS end to end: bootstrap, prompted baselines, a 20-step stop, the resumed run to completion, and adapter evaluation. The 27B baselines and training are queued. Results, costs and failure cases are in [RESULTS.md](RESULTS.md). Sections 1 and 3 describe the CPU checks made before the first GPU job.

## 1. What has been checked, and what has not

| Component | How it was checked | Result |
|---|---|---|
| Data acquisition | Downloaded every file at a pinned commit; SHA-256 recorded in [`manifests/sources.lock.json`](manifests/sources.lock.json) | Sizes match the published files byte for byte |
| Preparation | Ran on the full data twice | All 9 output files byte-identical; checksums in [`manifests/v1/data_record.json`](manifests/v1/data_record.json) |
| Leakage audits | Group, instruction, criterion, source, identical-input and question keys across splits | 0 violations |
| Prometheus prompt parser | Reparsed all 99,952 pre-rendered prompts against their published fields | 0 mismatches |
| Oak split | Port of the repository's `_stratified_split` | Reproduces 61/185/65 and the published first indices |
| Token lengths | Real Qwen3.5 tokenizer and chat template, all 117k examples | Max 3,055 tokens; none over 4,096 ([`manifests/v1/lengths.json`](manifests/v1/lengths.json)) |
| Scorers | Gold labels fed back as predictions on the dev splits | Perfect scores; RAGTruth span-F1 ceiling from quote matching 0.998 |
| Stop/resume | Tiny model, HF Trainer: interrupted run versus uninterrupted run | Identical losses, learning rates and final LoRA weights |
| MS-SWIFT 4.6.0 path | Tiny random-weight Qwen3.5 built from the real 9B config, tokenizer and processor; CPU; transformers 5.19 | Plugin loads; dataset rows match; LoRA on the language model only; stop at step 5, resume to 12 with the scheduler restored; adapter exported and loaded |
| Loss mask | MS-SWIFT's own `qwen3_5` encoding compared with the inference chat template | Prompt identical (including the empty think block); loss on target + `<|im_end|>` only |
| Not checked | vLLM backend, GPU memory and throughput, `flash-linear-attention` kernels, `qwen3_8` template rendering, the cluster environment pins (`requirements/cluster.txt`), PBS scripts on GaaS | Verify in the first jobs |

## 2. Running on NTU GaaS

All commands run from `packages/eval/training` in a clone that includes this directory.

### 2.1 One-time setup

Site facts checked on 27 October 2026 (recorded in [`pbs/env.example.sh`](pbs/env.example.sh)):

- **Project code:** `fs_ccds_tianwei.zhang`; the project runs until **2026-11-15**.
- **One GPU per project:** the project may run **one GPU job at a time**, and its 21 members share that slot. Jobs therefore run in sequence, so queue them as a dependency chain.
- **`gpu_free` routing:** it routes to `gpu_free_high` (1 GPU, at most 1 h, priority) or `gpu_free_normal` (at most 6 h), with one running job per user in each. The free pool is one 8-GPU node shared by 44 groups.
- **`/home`:** 932 GB quota, with weekly snapshots only.
- **Login node:** it must not run work. `gpu_datamover` jobs currently fail for every user with "invalid uid/gid", so the environment build and model downloads run in the first GPU job (`pbs/bootstrap.pbs`).
- **Windows' built-in `ssh`:** it fails with "Corrupted MAC on input" against this host. Force `-c aes128-gcm@openssh.com` or use Git's OpenSSH.

```bash
ssh YOUR_NTU_ID@gaas.hpc.ntu.edu.sg           # institutional VPN when off campus
cp pbs/env.example.sh pbs/env.sh              # set EVALTRAIN_PROJECT and EVALTRAIN_ROOT
bash pbs/pilot_chain.sh                       # bootstrap, then the whole 9B milestone (section 2.3)
```

The bootstrap job checks that the node can reach PyPI and Hugging Face, then:

1. builds the pinned venv;
2. stages Qwen3.5-9B;
3. runs `python -m evaltrain.gpu_smoke`;
4. stages Qwen3.8-27B with the remaining time; downloads resume, so a resubmission finishes it.

It exits non-zero if the venv, the 9B model or the smoke test is not ready, so chained jobs never start on a broken environment. The smoke test fails if transformers falls back to the PyTorch Gated DeltaNet kernel: that fallback is correct but more than ten times slower, and is reported only as a log message. `bash pbs/submit.sh setup` does the same staging through `gpu_datamover`, once that queue works. If `prepared/v1` is already present and matches `manifests/v1/data_record.json`, it is kept. Otherwise the job downloads and prepares the data itself; preparation loads a 1 GB JSON, about 5 GB of RAM. To reuse data prepared elsewhere, copy `prepared/v1` (680 MB) to `$EVALTRAIN_ROOT/prepared/v1` and check it with `python -m evaltrain.prepare --out <dir> --verify manifests/v1/data_record.json`.

Check the training render once per model before the first training job (no weights are loaded):

```bash
python -m evaltrain.swift_render --config configs/pilot_9b.yaml   # must report True / True
```

### 2.2 Prompted baselines (GPU jobs)

```bash
bash pbs/submit.sh eval configs/pilot_9b.yaml base+base-thinking    # several arms in one job, one queue wait
MEM=192gb bash pbs/submit.sh eval configs/main_27b.yaml base+base-thinking
```

Each writes `$EVALTRAIN_ROOT/runs/<run_id>/eval/<arm>-dev/{examples,predictions}.jsonl`, `report.md` and the inference metadata. `base-thinking` uses Qwen's thinking sampling (T=1.0, top-p 0.95, top-k 20, seeded); the others are greedy. Predictions are appended per batch, so an unfinished evaluation continues when resubmitted.

### 2.3 Pilot training with the stop/resume test

`pbs/pilot_chain.sh` queues this whole section: the baselines, a 20-step stop, three 1-hour resume chunks and the adapter evaluation, linked by `afterok` dependencies. The steps by hand:

```bash
STOP_AFTER_STEPS=20 WALLTIME=01:00:00 bash pbs/submit.sh train configs/pilot_9b.yaml   # job A: 20 steps, checkpoint, exit 0
bash pbs/submit.sh train configs/pilot_9b.yaml                                         # job B: resumes at 20, runs to 375, exports
```

Before submitting job B, inspect `runs/pilot-9b-v1/`:

- `jobs.jsonl`: job A `stopped / step_limit`, steps 0 to 20; after job B, steps 20 to 375, `completed`;
- `train/checkpoint-20/`: adapter, `optimizer.pt`, `scheduler.pt`, `rng_state.pth`, `trainer_state.json` and `CHECKPOINT_COMPLETE.json` (with the measured save time);
- `train/trainable_params.json`: LoRA tensors on `model.language_model` only;
- the PBS log: `nvidia-smi` output, MS-SWIFT's per-step `memory(GiB)` and speed, and the first learning rate logged by job B (it must continue the cosine schedule, not restart warm-up).

Longer runs: `bash pbs/submit.sh train configs/<config>.yaml 3` submits three jobs chained with `afterok`. Each stops for walltime with a full checkpoint, and the next resumes; a crash breaks the chain.

### 2.4 Adapter evaluation and comparison

```bash
bash pbs/submit.sh eval configs/pilot_9b.yaml adapter
RUN=$EVALTRAIN_ROOT/runs/pilot-9b-v1/eval
python -m evaltrain.evaluate --examples $RUN/base-dev/examples.jsonl \
  --predictions $RUN/base-dev/predictions.jsonl --compare $RUN/adapter-dev/predictions.jsonl --out $RUN/compare-base-adapter.json
```

`adapter-dev/report.json` contains `adapter_effect`. If adapter outputs match the base model on more than 95% of items, the adapter was probably not applied (vLLM #49354), and the result must not be reported. If outputs degrade into `!!!` or the valid rate collapses (vLLM #52568), merge the adapter (`swift export --adapters <run>/adapter --merge_lora true --output_dir <run>/merged`) and evaluate arm `merged`.

Select configurations on dev only. Score the test split once, at the end: `SPLIT=test FINAL=1 bash pbs/submit.sh eval <config> adapter` (and `base`). Each test access is logged in `test_access.jsonl`.

## 3. Running locally (CPU)

```bash
python -m venv .venv && .venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1
.venv/bin/pip install -r requirements/data.txt && .venv/bin/pip install -e .
export EVALTRAIN_ROOT=/some/non-synced/dir
python -m evaltrain.acquire --root $EVALTRAIN_ROOT
python -m evaltrain.prepare --raw $EVALTRAIN_ROOT/raw --out $EVALTRAIN_ROOT/prepared/v1
python -m evaltrain.lengths --prepared $EVALTRAIN_ROOT/prepared/v1 --tokenizer Qwen/Qwen3.5-9B --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a
EVALTRAIN_PREPARED=$EVALTRAIN_ROOT/prepared/v1 python -m pytest -q tests
```

The MS-SWIFT check (`configs/tiny_cpu_e2e.yaml`) needs a second environment with `ms-swift==4.6.0`, `qwen_vl_utils==0.0.14` and torchvision, a tiny model from `python tests/tiny_qwen35.py <dir with the 9B config/tokenizer files> $EVALTRAIN_ROOT/hf/tiny-qwen3.5`, and a small `prepared/tiny` sample with its own `lengths.json`.

## 4. Data

| Task | Source (revision) | Labels used | Train / dev / test rows (groups) | Notes |
|---|---|---|---|---|
| `prometheus_rubric` | Feedback Collection (`22a339f`, CC BY 4.0); held-out tests from `prometheus-eval` (`dcfb442`, Apache-2.0) | GPT-4 feedback and 1-5 score: **synthetic** | 95,522 (953) / 4,199 (42) / 2,000 | Grouped by instruction, rubric and criterion, so dev rubrics are unseen. Test = seen-rubric + unseen-rubric sets. The Hugging Face "Feedback-Bench" is not used: all its rows are training rows. 231 rows dropped (empty fields; criterion shared with the unseen-rubric test) |
| `ragtruth_grounding` | RAGTruth (`c103204`, MIT; source corpora keep their own terms) | Human spans, type, `implicit_true` | 13,453 (2,265) / 1,489 (250) / 2,675 (450) | `quality == "good"` only. Official test split (no shared sources, re-audited); dev = 10% of training sources. Annotator notes kept for failure analysis, not trained on |
| `oak_distractors` | Oak MCQ MinDiff (`737c060`, data OGL v3.0, code MIT) | Teacher 1-5 "minimally different distractors" score | 61 / 185 / 65 | The repository's exact split; only the 61 demonstration rows may ever be trained on |
| `leceval_slides` (opt-in) | LecEval (`3f75fe0`) | 3 raters x 4 criteria, slide image required | split by lecture | Slides derive from LPM (CC BY-NC-SA 4.0; videos under the YouTube licence) despite the MIT repository. **Confirm permitted use before** `acquire --include leceval` |

Oak attribution, required by OGL v3.0: *Contains data from Oak National Academy, derived from Clark, H.-B. et al. (2024), "Auto-Evaluation: A Critical Measure in Driving Improvements in Quality and Safety of AI-Generated Lesson Resources", AI + Open Education Initiative.*

**Data versions.** `pilot-9b-v1` and `main-27b-v1` were trained and scored on `prepared/v1`. That version repeats 800 Prometheus unseen-rubric test ids, because the source file numbers rows per instruction. The scorer pairs repeated ids in order of occurrence; see the disclosure in [RESULTS.md](RESULTS.md#6-test-split-scored-once). `prepared/v2` ([`manifests/v2`](manifests/v2/data_record.json)) gives those rows unique ids, and every train and dev file is byte-identical to v1. New experiments should set `data.version: v2`. Preparation now refuses repeated ids.

Targets are the datasets' own labels serialized as JSON. No rationale is generated for score-only data. Prompts are versioned in [`evaltrain/prompts.py`](evaltrain/prompts.py); the hash is recorded in every run and prediction file. Rendered examples are written to `prepared/v1/examples.md` and `render_samples.md`; they quote source text, so they stay outside Git.

## 5. Training set-up

`train.py` builds the mixture once, records `run.json` (config, training hash, Git revision, data and prompt hashes, package versions, GPU) and calls `swift sft`. Flags that matter:

- **Hub and output directory.** `--use_hf true` makes MS-SWIFT read the Hugging Face hub; its default is ModelScope. `--add_version false` keeps one output directory across PBS jobs.
- **No silent data loss.** `--strict true --lazy_tokenize false` stop MS-SWIFT from dropping over-length rows, or silently substituting random other rows when a row fails to encode. The plugin also stops training if MS-SWIFT's dataset size differs from the mixture.
- **Development data.** `--split_dataset_ratio 0`: development data comes from our grouped split.
- **Thinking.** `--add_non_thinking_prefix true` (default): the empty `<think>` block is part of the prompt and is masked out of the loss (`+ignore_empty_think`), matching inference with `enable_thinking=False`.
- **What trains.** `--target_modules all-linear --freeze_vit true --freeze_aligner true`: LoRA on the language model only; the plugin fails the run if anything else is trainable.

Walltime: the job records its start time before environment setup. The callback saves every `save_every_minutes`, and saves and stops when the next step would cut into `reserve_minutes` before the deadline; it does the same after SIGTERM. Each completed save writes `CHECKPOINT_COMPLETE.json`, and resumption uses only marked checkpoints. The schedule (epochs, warm-up, learning rate) is fixed by the config for the whole run. Changing any training setting changes the training hash, and resumption is then refused: use a new `run_id`.

Run directory: `run.json`, `data/train.jsonl` + `mixture.json`, `train/checkpoint-N/`, `train/{job_status,trainable_params,TRAINING_COMPLETE}.json`, `jobs.jsonl`, `adapter/` (+ `serving.json`), `eval/<arm>-<split>/`.

## 6. Evaluation

| Task | Metrics (bootstrap CIs resample groups) |
|---|---|
| Prometheus | Pearson, Spearman, exact agreement (unparseable = wrong), MAE, QWK, per test subset; agreement with GPT-4 labels |
| RAGTruth | Response-level precision/recall/F1; character-overlap span F1 (micro); unlocated-quote rate; conflict/baseless agreement; per task type |
| Oak | MAE, Spearman, QWK, exact; the dataset's own LLM baseline on the same rows as a reference |
| LecEval | Per criterion: Spearman, Pearson, MAE against the mean of in-scale ratings |

For 1-5 scores the report also gives probability-weighted expected scores from the score-token log-probabilities (`*_expected`). Valid-JSON and strict-JSON rates are reported per task. Published RAGTruth reference points (paper v2): fine-tuned Llama-2-13B response F1 78.7 / span F1 52.7; prompted GPT-4-turbo 63.4 / 28.3. Prometheus and Oak results are agreement with synthetic and teacher labels on these public tasks, not evidence of adult-course quality.

## 7. Batch inference contract

```bash
python -m evaltrain.infer --examples requests.jsonl --out results.jsonl --backend vllm \
  --model Qwen/Qwen3.5-9B --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a --adapter $RUN/adapter
```

Input: one `Example` per line. Inference reads `id`, `task`, `messages` (system + user, rendered from `prompts.py`) and `images`. Output, one line per id:

- the request's `id` and `task`;
- `raw`: the model text;
- `parsed`: the task-validated JSON object, or `null`;
- `valid` and `strict`: whether a JSON object could be recovered, and whether the whole answer was one;
- `error`;
- `score_dist`: digit probabilities per score key;
- token counts and latency.

`results.jsonl.meta.json` records model, revision, adapter, prompt version, thinking setting, sampling and package versions. Ids already present in `--out` are skipped, and `--deadline-epoch` stops between batches.

The LMS integration renders its review requests through the same templates. Use `RUBRIC` for criterion scoring against a reference and `GROUNDING` for source checks, so the adapter sees the format it was trained on. `serving.json` in the adapter directory states the base revision, template and `enable_thinking: false`. Under the cluster's open-data rule, only public course material may be sent to NTU batch jobs.

### Promotion into the application

A finished, evaluated adapter enters the app's model bundle through `python -m evaltrain.promote`. It copies the adapter, plus its dev-split evaluation as `reference/`, into `data/models/adapters/<name>/`, and refuses a run without `TRAINING_COMPLETE.json`, without an adapter evaluation, or whose `adapter_effect` check warns. After deployment, `python -m evaltrain.served_check` replays a deterministic subset of that reference against the running server and fails if the scores move by more than the tolerance (default 0.05). A wrong template, thinking left on, an adapter that silently did not load, or damaging quantization all fail this check. The surrounding release steps (`make models-lock`, `make models-verify`, `make served-check`) are in the [inference notes](../../../services/inference/README.md#release-steps).

## 8. Known risks and open items

- **Environment pins.** `requirements/cluster.txt` resolves the published constraints of vLLM 0.32.0, MS-SWIFT 4.6.0 and the Qwen recipe, but has not been installed on GaaS. flash-attn is only needed for packing; whether a wheel exists for torch 2.13 is unverified.
- **Unknown Qwen3.8 config field.** Qwen3.8-27B's config has `output_gate_type: "swish"`, which neither transformers 5.21 nor vLLM reads. A sensible 27B prompted baseline is the first check that the implementation matches the checkpoint.
- **Thinking-mode cost.** `base-thinking` adds up to 4,096 tokens per item; budget its walltime separately.
- **Memory profiling.** Profile memory in the first jobs before raising `per_device_batch_size` or enabling packing (each a new `run_id`). 27B BF16 weights alone are 55.6 GB.
- **Transfer gap.** Public-task agreement does not establish adult-course validity. Coverage, depth and objective alignment remain prompted, advisory judgments.
