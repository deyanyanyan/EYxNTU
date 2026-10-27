# Reviewer training results

**Status, 28 October 2026, 01:00 SGT.**

- **Training:** a 9B pilot and a 27B main run, both trained, resumed or completed, and evaluated on the development split.
- **Selection:** the **27B adapter** was selected on dev, then scored once on the full test split.

Sections 3–5 use the development split, which drove selection. Section 6 is the test split.

## 1. What was run

| | 9B pilot (`pilot-9b-v1`) | 27B main (`main-27b-v1`) |
|---|---|---|
| Base model | `Qwen/Qwen3.5-9B` @ `c2022362…`, template `qwen3_5` | `Qwen/Qwen3.8-27B` @ `1d4bf0f2…`, template `qwen3_8` |
| Training data | 3,000 RAGTruth (1,767 sources) + 3,000 Prometheus (935 rubrics) = 6,000 rows | All 13,453 RAGTruth (2,265 sources) + 3,000 Prometheus (935 rubrics) + Oak's 61 demonstration rows × 4 = 16,697 rows |
| LoRA | Rank 16 / alpha 32, all language-model linear layers: 43.3M of 9.45B parameters | Same settings: 116.7M of 27.47B parameters |
| Schedule | 375 steps | 1,044 steps |
| Provenance | Training hash `b142593f59480256`, code `09bec23b9a8b2ccc` | Training hash `14187ac9a2fd46dd`, code `6eb2df5410ae1255` |
| Jobs | 94878 + 94879 (training), 94882 (adapter evaluation) | 94893 (training), 95233 (adapter evaluation) |

The two runs share several settings:

- **Training:** one epoch, microbatch 1 × accumulation 16, learning rate 1e-4 with a cosine schedule and 5% warm-up, at most 4,096 tokens, thinking off, vision tower frozen.
- **Prompts:** both use prompt version `66e720f8e43d`. The code hashes differ only because evaluation and deployment code changed between the runs.
- **Hardware and software:** one NVIDIA H200 (141 GB) on NTU GaaS `gpu_free`, with torch 2.13.0, transformers 5.19.0, peft 0.20.0, ms-swift 4.6.0, vLLM 0.32.0 and flash-linear-attention 0.5.2.

**Evaluation set-up.** The development split is subsampled across all groups:

| Task | Items | Groups | What the groups are |
|---|---|---|---|
| Prometheus | 630 | 42 | rubrics, none seen in training |
| RAGTruth | 750 | 250 | source documents |
| Oak | 185 | 185 | questions |

Decoding is greedy. Intervals are 95% grouped bootstrap intervals (1,000 resamples of groups), and differences are paired on the same items.

The thinking arms use the template's thinking mode with Qwen's thinking sampling settings and a 16K-token budget. They run on a nested subset of 645 items: 200 per task, or all 185 for Oak.

## 2. Operational evidence

| | 9B | 27B |
|---|---|---|
| Stop / resume | Job 94878 stopped cleanly at step 20 with a complete checkpoint. Job 94879 resumed at step 20 (learning rate 9.993e-5 at step 25, continuing the cosine schedule) and finished at 375. The spare chained jobs exited at once | 0 → 1,044 in one job; the walltime callback was not needed |
| Step time, peak GPU memory | 5.8 s, 20.5 GiB | 10.3 s, 57.2 GiB |
| Checkpoint save | 0.6 s; time-based saves every 10 min | At most 1.7 s; 15 saves |
| Training GPU time | 42.5 min | 3.6 h |
| Render check (MS-SWIFT encoding = inference template, loss only on target + `<|im_end|>`) | 3/3 | 3/3 |
| Adapter applied in vLLM (share of outputs identical to base) | Yes (2.2%) | Yes (5.1%) |
| Inference, 1,565 dev items without thinking | 67 s | 192 s |

The GPU smoke test confirmed the flash-linear-attention kernel, not the slow PyTorch fallback. Every adapter output was valid JSON.

## 3. Development-split results

All 1,565 items:

| Task and metric | 9B untrained | 9B adapter | 27B untrained | **27B adapter** |
|---|---|---|---|---|
| RAGTruth response F1 | 0.654 | 0.825 | 0.746 | **0.859** |
| RAGTruth precision / recall | 0.487 / 0.997 | 0.863 / 0.791 | 0.602 / 0.981 | 0.890 / 0.830 |
| RAGTruth span F1 (character overlap) | 0.206 | 0.569 | 0.371 | **0.614** |
| Prometheus Pearson (unseen rubrics) | 0.773 | 0.889 | 0.817 | **0.913** |
| Prometheus exact agreement / MAE | 0.525 / 0.654 | 0.660 / 0.373 | 0.562 / 0.530 | 0.705 / 0.311 |
| Oak MAE (lower is better) | 1.93 | 2.06 | 1.93 | **1.12** |
| Oak QWK | 0.048 | 0.000 | 0.036 | **0.313** |

Paired differences, 95% intervals:

| Comparison | RAGTruth response F1 | RAGTruth span F1 | Prometheus Pearson | Oak MAE |
|---|---|---|---|---|
| 9B adapter − 9B untrained | +0.171 [+0.135, +0.210] | +0.363 [+0.311, +0.413] | +0.116 [+0.074, +0.159] | +0.13 [+0.02, +0.24] (worse) |
| 27B adapter − 27B untrained | +0.113 [+0.077, +0.151] | +0.243 [+0.201, +0.286] | +0.096 [+0.068, +0.122] | −0.81 [−1.02, −0.59] |
| 27B adapter − 9B adapter | +0.033 [+0.016, +0.051] | +0.045 [+0.010, +0.083] | +0.023 [+0.008, +0.040] | −0.94 [−1.16, −0.70] |

The 27B-versus-9B difference mixes model size with data: the 27B saw 4.5× more RAGTruth rows and the Oak demonstrations.

Against the strongest prompting, on the 645-item thinking subset:

| Arm (645 items) | RAGTruth response F1 | RAGTruth span F1 | Prometheus Pearson | Oak MAE |
|---|---|---|---|---|
| 9B untrained / with thinking | 0.633 / 0.741 | 0.171 / 0.379 | 0.791 / 0.813 | 1.93 / 1.83 |
| 27B untrained / with thinking | 0.734 / 0.655 | 0.293 / 0.325 | 0.817 / 0.806 | 1.93 / 1.81 |
| 9B adapter | 0.840 | 0.519 | 0.879 | 2.06 |

- **The 9B adapter beats every prompted arm on both trained tasks** (all paired intervals exclude zero). Against 9B thinking, for example, span F1 is +0.140 [+0.075, +0.208].
- **Thinking helped the untrained 9B on grounding but hurt the untrained 27B** (response F1 −0.080 [−0.109, −0.053]).
- **Thinking is expensive:** 574–1,103 s per 645 items, against 67–192 s per 1,565 without thinking.

RAGTruth by source type, as response F1 / span F1:

| Source type | 9B untrained | 9B adapter | 27B adapter |
|---|---|---|---|
| Data-to-text | 0.83 / 0.17 | 0.91 / 0.59 | 0.93 / 0.65 |
| QA | 0.53 / 0.31 | 0.72 / 0.57 | 0.75 / 0.60 |
| Summary | 0.49 / 0.12 | 0.67 / 0.47 | 0.75 / 0.56 |

**Reading the numbers.**

- **Grounding improved most, and on human labels.** The untrained models flag nearly every response (735 of 750 for the 9B), so their high recall carries little information. The adapters flag about 330.
- **For reference only:** the RAGTruth paper reports response F1 78.7 and span F1 52.7 for a fine-tuned Llama-2-13B, and 63.4 / 28.3 for prompted GPT-4-turbo. Those are **test-split** figures (section 6).
- **Prometheus results are agreement with GPT-4** on rubrics never seen in training.

## 4. Failure cases and regressions

- **Subtle unsupported claims are the main weakness.** Both adapters still catch most evident conflicts and additions, at span recall 0.77 (9B) and 0.81 (27B). Recall on subtle conflicts and subtle unsupported claims is only 0.36 (9B) and 0.38 (27B), against 0.68–0.75 for the untrained 9B, which flags nearly everything. On RAGTruth dev, the 27B adapter misses 61 hallucinated responses and raises 37 false alarms; the 9B misses 75 and raises 45. Subtle drift from the source is the error a course reviewer most needs to catch, so this is the first target for further work.
- **The 9B adapter's Oak collapse is fixed in the 27B.** The 9B adapter, trained without Oak, scored every Oak question 1. With the 61 demonstration rows, the 27B adapter's scores spread over 1–5 (18, 50, 30, 73 and 14 items per score). Its MAE of 1.12 also beats the Oak repository's own LLM judge on these items (1.35). The fix is confounded with model size; only a 9B run with the same data could separate the two.
- **The first thinking baseline was invalid.** A 4,096-token thinking budget cut off 26–75% of replies mid-reasoning; the 9B averaged 7,367 output tokens on RAGTruth once given room. That run is kept as `eval/base-thinking-4k-dev` and replaced by the 16K-budget runs above.

## 5. Selection

The **27B adapter** (`main-27b-v1`, `checkpoint-1044`) is best on every development metric. The **9B adapter** remains the smaller deployment option. It is within 0.02–0.05 of the 27B on the trained tasks at about a third of the inference time and GPU memory, but it is unusable on Oak-style questions without the Oak data.

## 6. Test split (scored once)

Jobs 95296 (9B) and 95297 (27B) ran each model untrained and with its adapter, once, on the full test partitions:

| Task | Test items | Source |
|---|---|---|
| Prometheus | 2,000 | 1,000 seen-rubric and 1,000 unseen-rubric (prometheus-eval) |
| RAGTruth | 2,675 | official test sources, quality "good" |
| Oak | 65 | the repository split |

`test_access.jsonl` in each run directory records exactly one access per arm. The selection in section 5 was made before these numbers existed and is not revisited.

| Test metric | 9B untrained | 9B adapter | 27B untrained | **27B adapter** |
|---|---|---|---|---|
| RAGTruth response F1 | 0.530 | 0.833 | 0.650 | **0.862** |
| RAGTruth precision / recall | 0.361 / 0.999 | 0.832 / 0.835 | 0.485 / 0.984 | 0.852 / 0.873 |
| RAGTruth span F1 | 0.151 | 0.593 | 0.300 | **0.641** |
| Prometheus Pearson, all 2,000 | 0.682 | 0.844 | 0.778 | **0.864** |
| Prometheus Pearson, seen / unseen rubrics | 0.695 / 0.671 | 0.854 / 0.835 | 0.787 / 0.770 | 0.870 / 0.858 |
| Prometheus exact agreement / MAE | 0.442 / 0.887 | 0.601 / 0.466 | 0.482 / 0.689 | 0.616 / 0.432 |
| Oak MAE (lower is better) | 1.91 | 2.00 | 1.82 | **1.02** |
| Oak Spearman / QWK | 0.065 / 0.028 | constant / 0.000 | 0.303 / 0.060 | 0.440 / 0.421 |

Paired test differences, 95% grouped intervals:

| Comparison | RAGTruth response F1 | RAGTruth span F1 | Prometheus Pearson | Oak MAE |
|---|---|---|---|---|
| 9B adapter − untrained | +0.303 [+0.275, +0.328] | +0.443 [+0.408, +0.471] | +0.162 [+0.135, +0.190] | +0.09 [−0.06, +0.28] |
| 27B adapter − untrained | +0.212 [+0.189, +0.233] | +0.342 [+0.307, +0.371] | +0.086 [+0.068, +0.108] | −0.80 [−1.19, −0.38] |
| 27B adapter − 9B adapter | +0.029 [+0.014, +0.044] | +0.048 [+0.027, +0.067] | +0.020 [+0.008, +0.033] | −0.99 [−1.35, −0.57] |

RAGTruth test results by source type, as response F1 / span F1:

| Source type | 27B untrained | 27B adapter | 9B adapter |
|---|---|---|---|
| Data-to-text | 0.81 / 0.28 | 0.92 / 0.65 | 0.90 / 0.59 |
| QA | 0.45 / 0.33 | 0.77 / 0.66 | 0.73 / 0.63 |
| Summary | 0.54 / 0.30 | 0.75 / 0.58 | 0.71 / 0.53 |

**Reading the test results.**

- **They confirm the dev conclusions,** with every trained-task gain statistically clear.
- **RAGTruth:** the RAGTruth paper's test-split figures are response F1 78.7 / span F1 52.7 for its fine-tuned Llama-2-13B and 63.4 / 28.3 for prompted GPT-4-turbo. Both adapters exceed the fine-tuned 13B, and the prompted 27B lands close to the prompted GPT-4-turbo.
- **The protocols are close but not identical:** we exclude the 25 test responses with quality other than "good", and the paper's span-F1 averaging is unverified. Treat the comparison as indicative.
- **Untrained precision is lower on test than on dev,** because the test split has fewer hallucinated responses (35% against 47%) and the untrained models flag nearly everything.
- **Oak's test set has only 65 questions,** hence the wide intervals. The 9B adapter is again constant (every score 1).

**Scoring correction, disclosed.** The Prometheus unseen-rubric test file numbers its rows per instruction (200 instructions × 5 responses), and the converter used that number as the example id. 800 test rows therefore shared ids, and the first scoring pass paired some Prometheus predictions with the wrong gold labels.

Predictions were not affected, because each row was generated from its own prompt, and nothing was re-generated. All four arms ran in a single uninterrupted pass with predictions in example order, which was checked for each arm. Scoring now pairs repeated ids in order of occurrence. The figures above are the corrected ones, recomputed from the saved predictions. RAGTruth, Oak and every development-split number used unique ids and are unchanged. The converter now assigns unique ids, and preparation fails on duplicates.

## 7. What these results do not show

- **Uncertainty comes from data sampling only.** Each run used one training seed.
- **Prometheus agreement is agreement with GPT-4,** not with human experts.
- **Nothing here measures adult-course quality.** Transfer to this project's adult-course material, its coverage judgments, and learner outcomes remain unmeasured. The reviewer's educational judgments stay advisory (see the [handoff](../TRAINING_HANDOFF.md)).
- **Prompted baselines used one prompt per task**, the same one the adapters were trained on. No prompt engineering was done for the baselines.

## 8. Next steps

1. Promote the 27B adapter, lock the bundle, and pass the served check before enabling the reviewer in the app ([release steps](../../../services/inference/README.md#release-steps)).
2. Target subtle grounding errors next. RAGTruth's subtle labels are scarce: about 2.5K subtle-baseless and 200 subtle-conflict spans in the whole dataset, test split included. Options to test on dev include up-weighting responses that contain subtle spans, and a second epoch.
