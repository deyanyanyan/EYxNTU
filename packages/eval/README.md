# Batch evaluation benchmark

The first evaluation slice scores saved course-generation runs after generation finishes. It reports per-lesson grounding, coherence, pedagogy, deterministic citation/slide/quiz checks, and course-level overlap. It does not update an asset, trigger a revision, gate approval/export, or change the application workflow.

The initial generator is the current local Qwen configuration. The optional judge is a separately configured model, initially Gemini. Bundles are model-neutral so later runs from other Gemini/frontier models or Qwen 30B can use the same scorer.

## Capture a run bundle

Run the baseline with an explicit data classification. Capture stores generated output, exact lesson evidence references, prompt snapshots, source and brief hashes, generator settings, and run metrics under the ignored data artifacts folder. The manifest contains hashes of the saved prompt and course snapshots; the scorer checks those hashes before evaluating.

~~~sh
docker compose --env-file .env -f infra/docker-compose.yml exec -T api \
  python /srv/scripts/course_baseline.py --capture-eval-inputs --eval-data-classification fictional \
  --generator-arm qwen7b-baseline
~~~

The runner prints the bundle directory, for example `/data/artifacts/eval/runs/<run-id>`. Capturing sensitive or unknown data is not supported by the hosted judge path; local-only bundles can be scored deterministically.
For a later quantization comparison, pass a descriptive `--quantization` label; it records metadata only and does not change the serving configuration.

## Score saved bundles

Deterministic-only scoring:

~~~sh
docker compose --env-file .env -f infra/docker-compose.yml exec -T api \
  python /srv/scripts/evaluate_batch.py /data/artifacts/eval/runs/<run-id>
~~~

To add Gemini as judge, configure these private `.env` values and recreate the API container so it receives them:

~~~dotenv
JUDGE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
JUDGE_API_KEY=<provider key>
JUDGE_MODEL=<provider model id>
~~~

Then run with `--judge`:

~~~sh
docker compose --env-file .env -f infra/docker-compose.yml exec -T api \
  python /srv/scripts/evaluate_batch.py /data/artifacts/eval/runs/<run-id> --judge
~~~

The batch scorer refuses a judge call unless each input manifest labels its data `fictional` or `public`. It never falls back to the generator if judge settings are missing. The benchmark prompt comes from the checked-in critique prompt files; the batch manifest records its hash and judge model.

Usage and latency are provider-reported where available. The report does not estimate monetary cost; add provider-specific pricing only after the model arms and billing units are selected.

Outputs are saved under `data/artifacts/eval/batches/<batch-id>/`:

- `scores.jsonl`: per-lesson dimensions, evidence-linked findings, deterministic counts, errors, and judge usage where the provider reports it.
- `courses.jsonl`: course-level repeated-evidence and near-duplicate diagnostics.
- `summary.csv` and `summary.md`: compact per-run scorecards.
- `manifest.json`: input run IDs, data classification, judge model, and evaluation prompt hash.
- `judge_prompt.json`: exact judge prompt snapshot when `--judge` is enabled.

Admins can score an existing captured run from **Admin > Evaluation**. The page lists saved run bundles, lets an admin choose deterministic checks and optional Gemini judging, tracks the scoring job, and opens the resulting report. It never starts generation or changes generated content. Gemini judging is enabled only when all `JUDGE_*` settings are present in the API environment; only runs marked public or fictional can be sent to the hosted judge.

## Interpreting results

Scores are exploratory. Lexical overlap, repeated citations, and slide-density thresholds are diagnostic heuristics, not proof of correctness or teaching quality. Review per-lesson examples; a course mean can hide a weak lesson. One captured run verifies the pipeline, not a reliable quality difference. Repeat generation conditions before making comparisons, and calibrate the judge against blind human ratings before treating scores as authoritative.

Before comparing RAG changes, prepare a frozen retrieval set with expected passages and preserve retrieval ranks/scores. For an in-loop critique experiment, generate the revised output as a separate workflow condition and score both the first draft and final output with this same post-generation benchmark.

## Future optimization directions

Use benchmark findings to select one change at a time: retrieval/evidence packing, prompts/templates, a critique-and-revision workflow, generator/model size, or quantization. If EY approves training, a frontier model can generate source-grounded teacher examples; a separate local SFT/LoRA or Q-LoRA training job is what changes the local model parameters. Keep training data separate from the benchmark holdout and record model, data, prompt, and hardware provenance. Fine-tuning is not a current project deliverable.
