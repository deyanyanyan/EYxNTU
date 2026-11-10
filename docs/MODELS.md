# Trained reviewer models

Two LoRA adapters that review generated courses. They flag slide text the source passages do not support, score lessons against a rubric with written feedback, and rate how well quiz distractors compete with the right answer. Both were fine-tuned on public data only: RAGTruth, Prometheus Feedback Collection and Oak's MCQ MinDiff set. The method and full results are in the [training results](../packages/eval/training/RESULTS.md).

| | Released | Pilot |
|---|---|---|
| Adapter | [`reviewer-main-27b-v1`](../data/models/adapters/reviewer-main-27b-v1) | [`reviewer-pilot-9b-v1`](../data/models/adapters/reviewer-pilot-9b-v1) |
| Base model | [`Qwen/Qwen3.8-27B`](https://huggingface.co/Qwen/Qwen3.8-27B) at `1d4bf0f2ff60…` (55.6 GB) | [`Qwen/Qwen3.5-9B`](https://huggingface.co/Qwen/Qwen3.5-9B) at `c2022362…` (19.3 GB) |
| LoRA | Rank 16, alpha 32, all language-model linear layers: 117M parameters, 467 MB | Same settings: 43M parameters, 173 MB |
| Bundle lock | [`infra/models.lock.json`](../infra/models.lock.json) | [`infra/models.pilot-9b.lock.json`](../infra/models.pilot-9b.lock.json) |
| Use | Course review | Comparison only: it scores every quiz question 1 |

## Trained versus base

These figures come from the held-out test split, scored once. "Base" is the same checkpoint without the adapter, with the same prompts, greedy decoding and thinking off.

| Metric (test items) | 9B base | 9B trained | 27B base | 27B trained |
|---|---|---|---|---|
| Grounding: response-level F1, higher is better (2,675) | 0.530 | 0.833 | 0.650 | **0.862** |
| Grounding: span-level F1, higher is better | 0.151 | 0.593 | 0.300 | **0.641** |
| Rubric: Pearson r with the reference scores, higher is better (2,000) | 0.682 | 0.844 | 0.778 | **0.864** |
| Distractors: mean absolute error on the 1–5 scale, lower is better (65) | 1.91 | 2.00 | 1.82 | **1.02** |

- **Statistically clear gains:** every 27B gain, and the 9B's grounding and rubric gains, have paired 95% grouped-bootstrap intervals that exclude zero.
- **Why the 27B is the release:** the 9B saw no distractor training data and did not improve on distractors. The 27B is also ahead on every other metric.
- **Reasoning did not close the gap:** on a 645-item dev subset, both base models with step-by-step reasoning (a 16K-token thinking budget) stayed below even the 9B adapter on grounding and rubric scoring. They also took over ten times as long per item.
- **What the numbers mean:** they measure agreement with public benchmark labels. The rubric labels are GPT-4's, not instructors' judgments of real courses, so the reviewer's course scores are advisory.

## Run them on your own GPU

You need a Linux host with an NVIDIA GPU, Docker with GPU support and Git LFS. The 27B needs one 80 GB GPU: an estimated 15 GB is left for the KV cache. It was evaluated on an H200. The [inference notes](../services/inference/README.md#run-the-released-reviewer) explain each step.

```sh
git lfs install    # once per machine
git lfs pull --include="data/models/adapters/reviewer-main-27b-v1/**" --exclude=""    # 467 MB
HF_HOME=data/models/hf hf download Qwen/Qwen3.8-27B --revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0
# .env: COMPOSE_PROFILES=cpu,gpu (Ollama keeps generating courses, vLLM serves the reviewer;
#       the VLLM_* defaults in .env.example already name this adapter)
make models-verify    # every base and adapter file against infra/models.lock.json
make up
make served-check ADAPTER=reviewer-main-27b-v1 MODEL=reviewer
# only if it passes: REVIEWER_ENABLED=true in .env, then make up again
```

Plain clones skip the adapters' weights (`.lfsconfig`), so teammates who only run the app on CPU are not affected.

To review in batches instead of serving live:

1. Export a course's review requests from the app: `python -m app.core.review export`.
2. Score them on any GPU machine with vLLM 0.32.0 and this repository's evaltrain package (`pip install -e packages/eval/training`): `python -m evaltrain.review_batch --adapter-dir data/models/adapters/reviewer-main-27b-v1 --requests … --out …`.
3. Load the findings back: `python -m app.core.review import`.

**Prompt contract.** The adapters only behave as measured when requests use the training templates in [`evaltrain/prompts.py`](../packages/eval/training/evaltrain/prompts.py) (version `66e720f8e43d`), with temperature 0 and thinking off. The app's reviewer client and `review_batch` both do this, and `serving.json` in each adapter records it.

## Licences

- **Base models:** Apache-2.0, from Qwen.
- **Training data:**
  - RAGTruth: MIT, though its source texts keep their own terms.
  - Prometheus Feedback Collection: CC BY 4.0.
  - Oak National Academy's MCQ MinDiff data: contains public sector information licensed under the Open Government Licence v3.0.
- **Reference files:** each adapter's `reference/` folder holds development-split items from these datasets, for the served check.
