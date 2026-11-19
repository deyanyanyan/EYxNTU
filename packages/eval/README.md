# Evaluation

The course reviewer: training, evaluation and batch review.

| Location | Contents |
|---|---|
| [`training/`](training/README.md) | The `evaltrain` package: public-data preparation, LoRA training on NTU GaaS, evaluation against base models, batch review (`evaltrain.review_batch`) and the release gate (`evaltrain.served_check`) |
| [`training/RESULTS.md`](training/RESULTS.md) | Method and full results of the 9B pilot and the released 27B reviewer |
| [`training/results/review-demo/`](training/results/review-demo/README.md) | The released reviewer's review of a mock course with planted errors |
| [`benchmark/`](benchmark/README.md) | Local Qwen 7B against hosted Gemini Flash as course writers, graded with the reviewer's prompts |

The released adapters and their headline results are described in [docs/MODELS.md](../../docs/MODELS.md). How the reviewer fits into the app is in [docs/HANDOVER.md](../../docs/HANDOVER.md#46-run-the-trained-reviewer).
